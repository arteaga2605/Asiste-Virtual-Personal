# main.py
import sys
import struct
import socket
import threading
import json
import time
import re
from collections import defaultdict
from datetime import datetime, timedelta
from config import (
    COMMUNICATION_PORT, AVATAR_ENABLED, HISTORY_LIMIT,
    OLLAMA_MODEL, OLLAMA_TRADING_MODEL, OLLAMA_SPORTS_MODEL,
    OLLAMA_HOST, SPORTS_REFRESH_INTERVAL
)
from tools.trading import (
    start_binance_stream, fetch_live_prices_for_news, build_news_prompt,
    SELECTED_CRYPTO, is_binance_stream_active, build_bitcoin_analysis_prompt, get_current_btc_price
)
from tools.memory import load_recent_history, save_message
from agent import process_user_message
from tools.sports import fetch_sports_data, build_sports_prompt, get_event_result, is_espn_available
from tools.predictions import (
    save_predictions, get_all_predictions,
    save_crypto_prediction, get_all_crypto_predictions, update_crypto_prediction_result
)
from tools.alerts import start_alert_monitor
from tools.business import generate_weekly_report, list_goals
import ollama

ollama_client = ollama.Client(host=OLLAMA_HOST)

SYSTEM_PROMPT_NEWS = (
    "Eres un analista experto en criptomonedas. Recibes precios en vivo, cambios 24h, "
    "volumen, RSI en tres marcos temporales (1h, 4h, 1d) y presión compradora de las criptomonedas seleccionadas. "
    "Debes seleccionar 3 'joyas ocultas' analizando RSI bajo, volumen alto y presión compradora. "
    "Explica por qué están infravaloradas y pueden rebotar. "
    "Responde solo con texto, sin herramientas ni funciones. Sé conciso."
)

SYSTEM_PROMPT_SPORTS = (
    "Eres un analista deportivo experto. Recibes datos de partidos del día (ligas, equipos, "
    "cuotas, estadísticas avanzadas) y debes devolver exclusivamente un JSON con tus predicciones, "
    "sin texto adicional. El formato debe ser: "
    '{"predictions": [{"game": "RESUMEN EXACTO DEL PARTIDO", "favorite": "nombre del equipo favorito", "score": "marcador estimado"}]}.'
    "Usa exactamente el RESUMEN que aparece en cada partido para el campo 'game'. "
    "**No devuelvas nunca una lista vacía**; debes hacer una predicción para cada partido."
)

SYSTEM_PROMPT_BTC = (
    "Eres un analista técnico experto en Bitcoin. Recibes datos detallados de BTC (precio, RSI, ATR, "
    "soportes, resistencias, Fibonacci, patrones de velas) y debes devolver exclusivamente un JSON con tu predicción. "
    "No añadas texto fuera del JSON. Responde solo con el JSON solicitado."
)

# ----- Caché deportivo -----
_sports_cache_lock = threading.Lock()
_cached_games = {}
_cached_meta = {}

def _refresh_sports_cache():
    time.sleep(5)
    while True:
        try:
            games_all, meta_all = fetch_sports_data(category_filter=None)
            with _sports_cache_lock:
                _cached_games[None] = games_all
                _cached_meta[None] = meta_all
            print(f"Cache deportivo actualizado (todos): {len(games_all)} partidos.")
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


def direct_ollama_query(system_prompt: str, user_prompt: str, model: str = OLLAMA_MODEL) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    response = ollama_client.chat(model=model, messages=messages, stream=False)
    return response["message"]["content"]


def _extract_first_json(text: str) -> str | None:
    """
    Intenta extraer el primer objeto JSON válido de un texto que puede contener
    texto adicional antes o después del JSON.
    """
    # Buscar la primera llave de apertura
    start = text.find('{')
    if start == -1:
        return None
    # Buscar la última llave de cierre a partir del inicio
    end = text.rfind('}')
    if end == -1:
        return None
    candidate = text[start:end+1]
    # Verificar que sea JSON válido
    try:
        json.loads(candidate)
        return candidate
    except:
        # Si falla, intentamos recortar hasta el último '}' que esté balanceado
        depth = 0
        last_valid_end = -1
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    last_valid_end = i
                    break
        if last_valid_end != -1:
            candidate2 = text[start:last_valid_end+1]
            try:
                json.loads(candidate2)
                return candidate2
            except:
                pass
    return None


def format_sports_predictions(predictions_json: str, games_data: list = None) -> str:
    """
    Convierte la respuesta JSON del modelo en un texto legible.
    Si el JSON no es válido o la lista está vacía, intenta extraer la información
    del texto bruto o devuelve el mensaje original.
    """
    # Intentar limpiar primero
    clean_json = _extract_first_json(predictions_json)
    if clean_json is None:
        return predictions_json if predictions_json.strip() else "El modelo no devolvió una respuesta válida."

    try:
        data = json.loads(clean_json)
        preds = data.get("predictions", [])
        if not preds:
            return "⚠️ El modelo devolvió un JSON sin predicciones. Respuesta original:\n\n" + predictions_json

        game_names = {}
        if games_data:
            for game in games_data:
                summary = game.get("summary", "")
                teams = game.get("teams", [])
                if len(teams) == 2:
                    names = []
                    for t in teams:
                        abbr = t.get("abbreviation", "")
                        name = t.get("name", "")
                        if abbr:
                            names.append(f"{name} ({abbr})")
                        else:
                            names.append(name)
                    game_names[summary] = " vs ".join(names)

        lines = ["🏈 **Análisis Deportivo del Día**\n"]
        for i, pred in enumerate(preds, 1):
            game_key = pred.get("game", "Partido desconocido")
            fav = pred.get("favorite", "Sin favorito")
            score = pred.get("score", "")
            score_str = f" ({score})" if score else ""
            display_game = game_names.get(game_key, game_key)
            lines.append(f"{i}. **{display_game}** → Favorito: **{fav}**{score_str}")
        return "\n".join(lines)
    except json.JSONDecodeError:
        return predictions_json


def get_system_status() -> str:
    ollama_ok = False
    try:
        ollama_client.list()
        ollama_ok = True
    except:
        pass
    binance_ok = is_binance_stream_active()
    espn_ok = is_espn_available()
    status = {"ollama": ollama_ok, "binance": binance_ok, "espn": espn_ok}
    return json.dumps(status)


def handle_client(conn, addr):
    try:
        raw_len = recv_exactly(conn, 4)
        (msg_len,) = struct.unpack("!I", raw_len)
        user_input = recv_exactly(conn, msg_len).decode("utf-8").strip()
        print(f"Pregunta recibida del avatar: {user_input}")

        history = load_recent_history(HISTORY_LIMIT)

        # ------------------ TRADING (deepseek‑r1:8b) ------------------
        if user_input.startswith("__NEWS__"):
            coins_df = fetch_live_prices_for_news(limit=11)
            news_prompt = build_news_prompt(coins_df)
            response = direct_ollama_query(SYSTEM_PROMPT_NEWS, news_prompt, model=OLLAMA_TRADING_MODEL)
            save_message("user", "📰 Noticias del día")
            save_message("assistant", response)
            print(f"Respuesta (noticias): {response[:100]}...")

        elif user_input.startswith("__BTC__"):
            btc_prompt = build_bitcoin_analysis_prompt()
            raw_response = direct_ollama_query(SYSTEM_PROMPT_BTC, btc_prompt, model=OLLAMA_TRADING_MODEL)

            # Limpiar JSON y guardar predicción
            clean_json = _extract_first_json(raw_response)
            if clean_json:
                try:
                    pred_json = json.loads(clean_json)
                    direction = pred_json.get("direction", "").lower()
                    target_price = float(pred_json.get("target_price", 0))
                    current_btc = get_current_btc_price()
                    if direction in ("bullish", "bearish") and current_btc:
                        save_crypto_prediction(direction, target_price, current_btc, raw_response)
                        print(f"Predicción BTC guardada: {direction} objetivo {target_price}")
                except Exception as e:
                    print(f"No se pudo guardar la predicción BTC: {e}")

            # Formatear respuesta para mostrar
            try:
                pred_json = json.loads(clean_json) if clean_json else json.loads(raw_response)
                direction = pred_json.get("direction", "desconocida")
                target = pred_json.get("target_price", "N/D")
                reasoning = pred_json.get("reasoning", "")
                response = f"₿ **Análisis Bitcoin**\n\nDirección esperada: **{direction.upper()}**\nPrecio objetivo: ${target}\n\n{reasoning}"
            except:
                response = raw_response

            save_message("user", "₿ Análisis Bitcoin")
            save_message("assistant", response)
            print(f"Respuesta (Bitcoin): {response[:100]}...")

        # ------------------ DEPORTES (qwen3:8b) ------------------
        elif user_input.startswith("__SPORTS__"):
            parts = user_input.split(":", 1)
            category = parts[1].strip() if len(parts) > 1 else None

            if category is None:
                with _sports_cache_lock:
                    games_data = _cached_games.get(None)
                    events_meta = _cached_meta.get(None)
                if games_data is None:
                    games_data, events_meta = fetch_sports_data(category_filter=None)
            else:
                games_data, events_meta = fetch_sports_data(category_filter=category)

            sports_prompt = build_sports_prompt(games_data)
            raw_response = direct_ollama_query(SYSTEM_PROMPT_SPORTS, sports_prompt, model=OLLAMA_SPORTS_MODEL)

            # Limpiar JSON para guardar
            clean_json = _extract_first_json(raw_response)
            if clean_json:
                try:
                    pred_json = json.loads(clean_json)
                    predictions = pred_json.get("predictions", [])
                    if predictions:
                        save_predictions(predictions, clean_json, events_meta)
                    else:
                        print("Predicciones vacías, no se guardan.")
                except json.JSONDecodeError:
                    print("No se pudo parsear la respuesta JSON del modelo. No se guardan predicciones estructuradas.")
            else:
                print("No se encontró JSON válido en la respuesta deportiva.")

            formatted_response = format_sports_predictions(raw_response, games_data)
            save_message("user", f"🏈 Análisis deportivo ({category or 'todos'})")
            save_message("assistant", formatted_response)
            response = formatted_response
            print(f"Respuesta (deportes): {response[:100]}...")

        # ------------------ RESTO DE OPCIONES (modelo general) ------------------
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

            # Reporte Bitcoin
            crypto_preds = get_all_crypto_predictions()
            response += "\n₿ **Predicciones de Bitcoin**\n\n"
            if not crypto_preds:
                response += "No hay predicciones de Bitcoin todavía."
            else:
                btc_aciertos = 0
                btc_fallos = 0
                btc_pendientes = 0
                detalles_btc = []

                now = datetime.now()
                for cp in crypto_preds:
                    pred_time_str = cp["timestamp"]
                    try:
                        pred_time = datetime.fromisoformat(pred_time_str)
                    except:
                        pred_time = None

                    if cp["checked"]:
                        if cp["result"] == "acierto":
                            btc_aciertos += 1
                            detalles_btc.append(f"✅ {cp['direction']} → acierto")
                        else:
                            btc_fallos += 1
                            detalles_btc.append(f"❌ {cp['direction']} → fallo")
                        continue

                    if pred_time and (now - pred_time) < timedelta(hours=24):
                        btc_pendientes += 1
                        detalles_btc.append(f"⏳ {cp['direction']} (pendiente, predicho {pred_time.strftime('%d/%m %H:%M')})")
                        continue

                    current_price = get_current_btc_price()
                    if current_price is None:
                        btc_pendientes += 1
                        detalles_btc.append(f"⏳ {cp['direction']} (sin precio actual)")
                        continue

                    predicted_direction = cp["direction"]
                    old_price = cp["current_price"]
                    if predicted_direction == "bullish" and current_price > old_price:
                        update_crypto_prediction_result(cp["id"], "acierto")
                        btc_aciertos += 1
                        detalles_btc.append(f"✅ {cp['direction']} (subió de ${old_price:.2f} a ${current_price:.2f})")
                    elif predicted_direction == "bearish" and current_price < old_price:
                        update_crypto_prediction_result(cp["id"], "acierto")
                        btc_aciertos += 1
                        detalles_btc.append(f"✅ {cp['direction']} (bajó de ${old_price:.2f} a ${current_price:.2f})")
                    else:
                        update_crypto_prediction_result(cp["id"], "fallo")
                        btc_fallos += 1
                        detalles_btc.append(f"❌ {cp['direction']} (precio ahora ${current_price:.2f})")

                response += f"🔹 **Total Bitcoin**: {btc_aciertos} aciertos, {btc_fallos} fallos"
                if btc_pendientes > 0:
                    response += f", {btc_pendientes} pendientes"
                response += "\n"
                for det in detalles_btc:
                    response += f"  {det}\n"

        elif user_input.startswith("__GOALS__"):
            goals = list_goals(active_only=True)
            if not goals:
                response = "No tienes metas activas en este momento. Puedes añadir una usando el chat (ej. 'Añade la meta: aumentar productividad')."
            else:
                lines = ["🎯 **Metas actuales**\n"]
                for g in goals:
                    lines.append(f"- {g['description']}: {g['current_value']}/{g['target_value']} {g['unit']}")
                response = "\n".join(lines)

        elif user_input.startswith("__WEEKLY__"):
            response = generate_weekly_report()

        elif user_input.startswith("__HISTORY__"):
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
                    lines.append("")
                response = "\n".join(lines)

        elif user_input.startswith("__STATUS__"):
            response = get_system_status()

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
    start_binance_stream(SELECTED_CRYPTO)
    print("Stream Binance activo (criptos seleccionadas).")

    start_alert_monitor(interval_minutes=10)
    print("Monitor de alertas iniciado (criptos + tareas).")

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