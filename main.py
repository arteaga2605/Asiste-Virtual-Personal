# main.py
import sys
import struct
import socket
import threading
import json
from config import COMMUNICATION_PORT, AVATAR_ENABLED, HISTORY_LIMIT, OLLAMA_MODEL, OLLAMA_HOST
from tools.trading import start_binance_stream, get_live_price
from tools.memory import load_recent_history, save_conversation, save_message
from agent import process_user_message
from tools.sports import fetch_sports_data, build_sports_prompt, get_event_result
from tools.predictions import save_predictions, get_all_predictions
import ollama

ollama_client = ollama.Client(host=OLLAMA_HOST)

SYSTEM_PROMPT_NEWS = (
    "Eres un analista experto en criptomonedas. Recibes precios en vivo y debes sugerir "
    "3 criptomonedas 'joyas ocultas' para invertir a 1 día, explicando brevemente cada una. "
    "Responde solo con texto, sin herramientas ni funciones. Sé conciso."
)

SYSTEM_PROMPT_SPORTS = (
    "Eres un analista deportivo experto. Recibes datos de partidos del día (ligas, equipos, "
    "cuotas) y debes devolver exclusivamente un JSON con tus predicciones, "
    "sin texto adicional. El formato debe ser: "
    '{"predictions": [{"game": "nombre del partido", "favorite": "nombre del equipo favorito"}]}.'
)


def recv_exactly(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Conexión cerrada inesperadamente")
        buf += chunk
    return buf


def fetch_live_prices():
    symbols = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT",
        "ATOMUSDT", "MATICUSDT", "ADAUSDT", "DOTUSDT", "AVAXUSDT"
    ]
    prices = {}
    for sym in symbols:
        price = get_live_price(sym)
        if price is not None:
            prices[sym] = price
    return prices


def build_news_prompt(prices_dict):
    price_lines = "\n".join([f"- {sym}: ${price:.4f}" for sym, price in prices_dict.items()])
    if not price_lines:
        price_lines = "No se pudieron obtener precios en vivo en este momento."
    prompt = (
        "A continuación tienes los precios actuales (en USDT) de varias criptomonedas "
        f"obtenidos en tiempo real desde Binance:\n\n{price_lines}\n\n"
        "Sugiere 3 criptomonedas 'joyas ocultas' para invertir a 1 día, explicando brevemente cada una."
    )
    return prompt


def direct_ollama_query(system_prompt: str, user_prompt: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    response = ollama_client.chat(model=OLLAMA_MODEL, messages=messages, stream=False)
    return response["message"]["content"]


def format_sports_predictions(predictions_json: str) -> str:
    """
    Convierte la respuesta JSON del modelo deportivo en un texto legible.
    Si el JSON no se puede parsear, devuelve el texto original.
    """
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
        # Si falla el parseo, mostramos el texto original (puede ser un error)
        return predictions_json


def handle_client(conn, addr):
    try:
        raw_len = recv_exactly(conn, 4)
        (msg_len,) = struct.unpack("!I", raw_len)
        user_input = recv_exactly(conn, msg_len).decode("utf-8").strip()
        print(f"Pregunta recibida del avatar: {user_input}")

        history = load_recent_history(HISTORY_LIMIT)

        if user_input.startswith("__NEWS__"):
            live_prices = fetch_live_prices()
            news_prompt = build_news_prompt(live_prices)
            response = direct_ollama_query(SYSTEM_PROMPT_NEWS, news_prompt)
            save_message("user", "📰 Noticias del día")
            save_message("assistant", response)
            print(f"Respuesta (noticias): {response[:100]}...")

        elif user_input.startswith("__SPORTS__"):
            games_data, events_meta = fetch_sports_data()
            sports_prompt = build_sports_prompt(games_data)
            raw_response = direct_ollama_query(SYSTEM_PROMPT_SPORTS, sports_prompt)

            # Intentar guardar las predicciones estructuradas
            try:
                pred_json = json.loads(raw_response)
                predictions = pred_json.get("predictions", [])
                save_predictions(predictions, raw_response, events_meta)
            except json.JSONDecodeError:
                print("No se pudo parsear la respuesta JSON del modelo. No se guardan predicciones estructuradas.")

            # Convertir la respuesta JSON a texto legible para mostrar en el avatar
            formatted_response = format_sports_predictions(raw_response)

            save_message("user", "🏈 Análisis deportivo del día")
            save_message("assistant", formatted_response)
            response = formatted_response   # esto se enviará al avatar
            print(f"Respuesta (deportes): {response[:100]}...")

        elif user_input.startswith("__REPORT__"):
            all_preds = get_all_predictions()
            if not all_preds:
                response = "No hay predicciones guardadas aún. Usa primero la opción Deporte."
            else:
                aciertos = 0
                fallos = 0
                resultados = []
                for pred in all_preds:
                    event_id = pred["event_id"]
                    sport = pred["sport"]
                    league_slug = pred.get("league_slug", "")
                    result = get_event_result(sport, league_slug, event_id)
                    if result and result.get("winner"):
                        real_winner = result["winner"]
                        predicted = pred["favorite"]
                        if predicted and real_winner and predicted.lower() == real_winner.lower():
                            aciertos += 1
                            resultados.append(f"✅ {pred['league']}: {pred['teams']} → Predijo **{predicted}**, ganó **{real_winner}**")
                        else:
                            fallos += 1
                            resultados.append(f"❌ {pred['league']}: {pred['teams']} → Predijo **{predicted}**, ganó **{real_winner}**")
                    else:
                        resultados.append(f"⏳ {pred['league']}: {pred['teams']} → Partido aún no finalizado")
                response = f"📊 **Reporte de predicciones**\n\nAciertos: {aciertos}\nFallos: {fallos}\n\n" + "\n".join(resultados)
            # No guardamos en historial conversacional este reporte para no mezclar
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