# main.py
import sys
import struct
import socket
import threading
from config import COMMUNICATION_PORT, AVATAR_ENABLED, HISTORY_LIMIT, OLLAMA_MODEL, OLLAMA_HOST
from tools.trading import start_binance_stream, get_live_price
from tools.memory import load_recent_history, save_conversation, save_message
from agent import process_user_message
from tools.sports import fetch_sports_data, build_sports_prompt
import ollama

# Cliente Ollama (el mismo que usa agent.py)
ollama_client = ollama.Client(host=OLLAMA_HOST)

# System prompts especializados
SYSTEM_PROMPT_NEWS = (
    "Eres un analista experto en criptomonedas. Recibes precios en vivo y debes sugerir "
    "3 criptomonedas 'joyas ocultas' para invertir a 1 día, explicando brevemente cada una. "
    "Responde solo con texto, sin herramientas ni funciones. Sé conciso."
)

SYSTEM_PROMPT_SPORTS = (
    "Eres un analista deportivo experto. Recibes datos de partidos del día (ligas, equipos, "
    "cuotas) y debes indicar para cada partido qué equipo tiene más probabilidades de ganar, "
    "con una breve razón. Responde solo con texto, sin herramientas ni funciones. Sé conciso."
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
    """Envía un prompt directamente a Ollama, sin herramientas ni historial."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    response = ollama_client.chat(model=OLLAMA_MODEL, messages=messages, stream=False)
    return response["message"]["content"]


def handle_client(conn, addr):
    try:
        raw_len = recv_exactly(conn, 4)
        (msg_len,) = struct.unpack("!I", raw_len)
        user_input = recv_exactly(conn, msg_len).decode("utf-8").strip()
        print(f"Pregunta recibida del avatar: {user_input}")

        # Cargar historial de conversación reciente (memoria persistente)
        history = load_recent_history(HISTORY_LIMIT)

        # --- Manejadores especiales sin herramientas ---
        if user_input.startswith("__NEWS__"):
            live_prices = fetch_live_prices()
            news_prompt = build_news_prompt(live_prices)
            response = direct_ollama_query(SYSTEM_PROMPT_NEWS, news_prompt)
            # Guardar en el historial esta interacción
            save_message("user", "📰 Noticias del día")
            save_message("assistant", response)
            print(f"Respuesta (noticias): {response[:100]}...")

        elif user_input.startswith("__SPORTS__"):
            sports_data = fetch_sports_data()
            sports_prompt = build_sports_prompt(sports_data)
            response = direct_ollama_query(SYSTEM_PROMPT_SPORTS, sports_prompt)
            save_message("user", "🏈 Análisis deportivo del día")
            save_message("assistant", response)
            print(f"Respuesta (deportes): {response[:100]}...")

        else:
            # Conversación normal con herramientas y memoria
            response, updated_history = process_user_message(user_input, history)
            # Persistir solo los mensajes nuevos (user + assistant)
            num_old = len(history)
            new_messages = updated_history[num_old:]
            for msg in new_messages:
                save_message(msg["role"], msg["content"])
            print(f"Respuesta: {response[:100]}...")

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