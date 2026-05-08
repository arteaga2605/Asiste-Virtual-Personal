# main.py
import sys
import struct
import socket
import threading
import json
import time
from collections import defaultdict
from config import COMMUNICATION_PORT, AVATAR_ENABLED, HISTORY_LIMIT, OLLAMA_MODEL, OLLAMA_HOST, SPORTS_REFRESH_INTERVAL
from tools.trading import start_binance_stream, fetch_live_prices_for_news, build_news_prompt
from tools.memory import load_recent_history, save_message
from agent import process_user_message
from tools.sports import fetch_sports_data, build_sports_prompt, get_event_result
from tools.predictions import save_predictions, get_all_predictions
from tools.alerts import start_alert_monitor
import ollama

ollama_client = ollama.Client(host=OLLAMA_HOST)

SYSTEM_PROMPT_NEWS = (
    "Eres un analista experto en criptomonedas. Recibes precios en vivo, cambios 24h, "
    "volumen y RSI en tres marcos temporales (1h, 4h, 1d) de muchas criptomonedas. "
    "Debes seleccionar 3 'joyas ocultas' analizando RSI bajo y volumen alto. "
    "Explica por qué están infravaloradas y pueden rebotar. "
    "Responde solo con texto, sin herramientas ni funciones. Sé conciso."
)

SYSTEM_PROMPT_SPORTS = (
    "Eres un analista deportivo experto. Recibes datos de partidos del día (ligas, equipos, "
    "cuotas) y debes devolver exclusivamente un JSON con tus predicciones, "
    "sin texto adicional. El formato debe ser: "
    '{"predictions": [{"game": "nombre del partido", "favorite": "nombre del equipo favorito"}]}.'
)

# ----- Caché de datos deportivos (actualizado cada 45 min) -----
_sports_cache_lock = threading.Lock()
_cached_games = None
_cached_meta = None

def _refresh_sports_cache():
    """Se ejecuta en un hilo independiente para mantener los datos frescos."""
    global _cached_games, _cached_meta
    time.sleep(5)  # dar tiempo al inicio
    while True:
        try:
            games, meta = fetch_sports_data()
            with _sports_cache_lock:
                _cached_games = games
                _cached_meta = meta
            print(f"Cache deportivo actualizado: {len(games)} partidos.")
        except Exception as e:
            print(f"Error refrescando cache deportivo: {e}")
        time.sleep(SPORTS_REFRESH_INTERVAL)


def recv_exactly(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Conexión cerrada inesperadamente")
        buf += chunk
    return buf


def direct_ollama_query(system_prompt: str, user_prompt: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    response = ollama_client.chat(model=OLLAMA_MODEL, messages=messages, stream=False)
    return response["message"]["content"]


def format_sports_predictions(predictions_json: str) -> str:
    try:
        data = json.loads(predictions_json)
        preds = data.get("predictions", [])
        if not preds:
            return "No se recibieron predicciones estructuradas."
        lines = ["🏈 **Análisis Deportivo del Día**\n"]
        for i, pred in enumerate(preds, 1):
            game = pred.get("game", "Partido desconocido")
            fav = pred.get("favorite", "Sin favorito")
            lines.append(f"{i}. **{game}** → Favorito: **{fav}**")
        return "\n".join(lines)
    except Exception:
        return predictions_json


def handle_client(conn, addr):
    try:
        raw_len = recv_exactly(conn, 4)
        (msg_len,) = struct.unpack("!I", raw_len)
        user_input = recv_exactly(conn, msg_len).decode("utf-8").strip()
        print(f"Pregunta recibida del avatar: {user_input}")

        history = load_recent_history(HISTORY_LIMIT)

        if user_input.startswith("__NEWS__"):
            coins_df = fetch_live_prices_for_news(limit=50)
            news_prompt = build_news_prompt(coins_df)
            response = direct_ollama_query(SYSTEM_PROMPT_NEWS, news_prompt)
            save_message("user", "📰 Noticias del día")
            save_message("assistant", response)
            print(f"Respuesta (noticias): {response[:100]}...")

        elif user_input.startswith("__SPORTS__"):
            # Usar datos del caché, o fetch inmediato si no hay
            with _sports_cache_lock:
                games_data = _cached_games
                events_meta = _cached_meta
            if games_data is None:
                games_data, events_meta = fetch_sports_data()
            sports_prompt = build_sports_prompt(games_data)
            raw_response = direct_ollama_query(SYSTEM_PROMPT_SPORTS, sports_prompt)

            try:
                pred_json = json.loads(raw_response)
                predictions = pred_json.get("predictions", [])
                save_predictions(predictions, raw_response, events_meta)
            except json.JSONDecodeError:
                print("No se pudo parsear la respuesta JSON del modelo. No se guardan predicciones estructuradas.")

            formatted_response = format_sports_predictions(raw_response)
            save_message("user", "🏈 Análisis deportivo del día")
            save_message("assistant", formatted_response)
            response = formatted_response
            print(f"Respuesta (deportes): {response[:100]}...")

        elif user_input.startswith("__REPORT__"):
            all_preds = get_all_predictions()
            if not all_preds:
                response = "No hay predicciones guardadas aún. Usa primero la opción Deporte."
            else:
                league_stats = defaultdict(lambda: {"aciertos": 0, "fallos": 0, "pendientes": 0, "detalles": []})
                total_aciertos = 0
                total_fallos = 0
                total_pendientes = 0

                for pred in all_preds:
                    event_id = pred["event_id"]
                    sport = pred["sport"]
                    league = pred["league"]
                    league_slug = pred.get("league_slug", "")
                    result = get_event_result(sport, league_slug, event_id)
                    predicted = pred["favorite"]
                    teams = pred["teams"]

                    if result and result.get("winner"):
                        real_winner = result["winner"]
                        if predicted and real_winner and predicted.lower() == real_winner.lower():
                            league_stats[league]["aciertos"] += 1
                            total_aciertos += 1
                            league_stats[league]["detalles"].append(
                                f"✅ {teams} → Predijo **{predicted}**, ganó **{real_winner}**"
                            )
                        else:
                            league_stats[league]["fallos"] += 1
                            total_fallos += 1
                            league_stats[league]["detalles"].append(
                                f"❌ {teams} → Predijo **{predicted}**, ganó **{real_winner}**"
                            )
                    else:
                        league_stats[league]["pendientes"] += 1
                        total_pendientes += 1
                        league_stats[league]["detalles"].append(
                            f"⏳ {teams} → Partido aún no finalizado"
                        )

                response = "📊 **Reporte de predicciones**\n\n"
                response += f"🔹 **Total general**: {total_aciertos} aciertos, {total_fallos} fallos"
                if total_pendientes > 0:
                    response += f", {total_pendientes} pendientes"
                response += "\n\n"

                for league, stats in sorted(league_stats.items()):
                    response += f"**{league}**: {stats['aciertos']} aciertos, {stats['fallos']} fallos"
                    if stats['pendientes'] > 0:
                        response += f", {stats['pendientes']} pendientes"
                    response += "\n"
                    for det in stats["detalles"]:
                        response += f"  {det}\n"
                    response += "\n"

        elif user_input.startswith("__HISTORY__"):
            # Cargar más mensajes que el límite habitual (últimos 100)
            full_history = load_recent_history(limit=100)
            if not full_history:
                response = "No hay conversaciones guardadas todavía."
            else:
                lines = ["📜 **Historial de conversación**\n"]
                for msg in full_history:
                    role = msg["role"]
                    content = msg["content"]
                    if role == "user":
                        lines.append(f"🧑 **Tú**: {content}")
                    elif role == "assistant":
                        lines.append(f"🤖 **Asistente**: {content}")
                    elif role == "tool":
                        lines.append(f"🔧 **Herramienta**: {content}")
                    lines.append("")  # línea en blanco
                response = "\n".join(lines)
            # No guardamos esto en la memoria para no mezclar

        else:
            response, updated_history = process_user_message(user_input, history)
            num_old = len(history)
            new_messages = updated_history[num_old:]
            for msg in new_messages:
                save_message(msg["role"], msg["content"])
            print(f"Respuesta: {response[:100]}...")

        response_bytes = response.encode("utf-8")
        conn.sendall(struct.pack("!I", len(response_bytes)))
        conn.sendall(response_bytes)

    except Exception as e:
        print(f"Error en cliente: {e}")
        try:
            error_msg = f"Error del servidor: {e}".encode("utf-8")
            conn.sendall(struct.pack("!I", len(error_msg)))
            conn.sendall(error_msg)
        except:
            pass
    finally:
        conn.close()


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("localhost", COMMUNICATION_PORT))
    server.listen(5)
    print(f"Servidor IA escuchando en puerto {COMMUNICATION_PORT}...")
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


def main():
    print("Iniciando asistente virtual...")
    start_binance_stream(["btcusdt", "ethusdt", "bnbusdt", "solusdt", "linkusdt",
                          "atomusdt", "maticusdt", "adausdt", "dotusdt", "avaxusdt"])
    print("Stream Binance activo (10 pares).")

    # Monitor de alertas automáticas
    start_alert_monitor(interval_minutes=10)
    print("Monitor de alertas iniciado.")

    # Hilo de refresco de caché deportivo (cada 45 min)
    threading.Thread(target=_refresh_sports_cache, daemon=True).start()
    print("Refresco automático de datos deportivos iniciado.")

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    if AVATAR_ENABLED:
        import subprocess
        import os
        avatar_path = os.path.join(os.path.dirname(__file__), "avatar.py")
        try:
            subprocess.Popen([sys.executable, avatar_path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Avatar lanzado.")
        except Exception as e:
            print(f"No se pudo lanzar el avatar: {e}")

    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("Cerrando servidor...")


if __name__ == "__main__":
    main()