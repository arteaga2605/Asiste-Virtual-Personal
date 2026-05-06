# main.py
import sys
import struct
import socket
import threading
from config import COMMUNICATION_PORT, AVATAR_ENABLED, HISTORY_LIMIT
from tools.trading import start_binance_stream, get_live_price
from tools.memory import load_recent_history, save_conversation, save_message
from agent import process_user_message
from tools.sports import fetch_sports_data, build_sports_prompt  # <-- nueva importación


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
        "Eres un analista experto en criptomonedas. A continuación tienes los precios actuales "
        f"(en USDT) de varias criptomonedas obtenidos en tiempo real desde Binance:\n\n"
        f"{price_lines}\n\n"
        "Basándote **exclusivamente** en estos precios y en tu conocimiento de mercado, "
        "sugiere 3 criptomonedas que consideres 'joyas ocultas' para invertir a un plazo de 1 día. "
        "Explica brevemente por qué cada una podría tener un buen desempeño hoy o mañana. "
        "Sé conciso y no te salgas del análisis con datos reales. "
        "No puedes recomendar comprar o vender; solo ofrecer una opinión informada."
    )
    return prompt


def handle_client(conn, addr):
    try:
        raw_len = recv_exactly(conn, 4)
        (msg_len,) = struct.unpack("!I", raw_len)
        user_input = recv_exactly(conn, msg_len).decode("utf-8").strip()
        print(f"Pregunta recibida del avatar: {user_input}")

        # Cargar historial de conversación reciente (memoria persistente)
        history = load_recent_history(HISTORY_LIMIT)

        # Detectar si es una solicitud especial
        if user_input.startswith("__NEWS__"):
            live_prices = fetch_live_prices()
            prompt_ia = build_news_prompt(live_prices)
            response, updated_history = process_user_message(prompt_ia, history)

        elif user_input.startswith("__SPORTS__"):          # <-- NUEVA OPCIÓN
            sports_data = fetch_sports_data()
            prompt_ia = build_sports_prompt(sports_data)
            response, updated_history = process_user_message(prompt_ia, history)

        elif user_input:
            response, updated_history = process_user_message(user_input, history)
        else:
            response = ""
            updated_history = history

        print(f"Respuesta: {response[:100]}...")

        # Guardar en base de datos los mensajes nuevos
        num_old = len(history)
        new_messages = updated_history[num_old:]
        for msg in new_messages:
            save_message(msg["role"], msg["content"])

        # Enviar respuesta al avatar
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