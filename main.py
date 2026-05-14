# main.py
import sys
import struct
import socket
import threading
import json
import time
import unicodedata
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from config import (
    COMMUNICATION_PORT, AVATAR_ENABLED, HISTORY_LIMIT,
    OLLAMA_MODEL, OLLAMA_TRADING_MODEL, OLLAMA_SPORTS_MODEL,
    OLLAMA_HOST, SPORTS_REFRESH_INTERVAL
)
from tools.trading import (
    start_binance_stream, fetch_live_prices_for_news, build_news_prompt,
    SELECTED_CRYPTO, is_binance_stream_active, build_crypto_analysis_prompt, get_current_crypto_price
)
from tools.memory import load_recent_history, save_message
from agent import process_user_message
from tools.sports import fetch_sports_data, build_sports_prompt, get_event_result, is_espn_available, normalize_text
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
    '{"predictions": [{"game": "RESUMEN EXACTO DEL PARTIDO", "favorite": "nombre completo del equipo", '
    '"score": "marcador estimado", "confidence": número entre 0 y 100}]}.'
    "Usa exactamente el RESUMEN que aparece en cada partido para el campo 'game'. "
    "**No devuelvas nunca una lista vacía**; debes hacer una predicción para cada partido."
)

SYSTEM_PROMPT_CRYPTO = (
    "Eres un analista técnico experto en criptomonedas. Recibes datos detallados de una moneda "
    "(precio, RSI, ATR, soportes, resistencias, Fibonacci, patrones de velas) y debes devolver "
    "exclusivamente un JSON con tu predicción. No añadas texto fuera del JSON."
)

SYSTEM_PROMPT_INCOME = (
    "Eres un asesor experto en generación de ingresos y emprendimiento. "
    "Conoces todas las herramientas de este asistente virtual: análisis de criptomonedas (trading, "
    "indicadores técnicos), predicciones deportivas (con cuotas y estadísticas), gestión empresarial "
    "(metas, tareas, contactos) y programación en Python. "
    "El usuario ha utilizado el asistente durante un tiempo y ahora quiere ideas para ganar dinero extra "
    "aprovechando sus habilidades y las funcionalidades que más usa. "
    "Analiza el resumen de uso que se te proporciona y sugiere 3 maneras concretas, realistas y "
    "accionables de generar ingresos adicionales. Para cada idea, explica brevemente en qué consiste, "
    "cómo puede implementarla con la ayuda del asistente y qué potencial de ganancias podría tener. "
    "Sé específico, práctico y motivador. Responde solo con texto, sin herramientas ni funciones."
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
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    response = ollama_client.chat(model=model, messages=messages, stream=False)
    return response["message"]["content"]


def _extract_first_json(text: str) -> str | None:
    start = text.find('{')
    if start == -1:
        return None
    end = text.rfind('}')
    if end == -1:
        return None
    candidate = text[start:end+1]
    try:
        json.loads(candidate)
        return candidate
    except:
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
    clean_json = _extract_first_json(predictions_json)
    if clean_json is None:
        return predictions_json if predictions_json.strip() else "El modelo no devolvió una respuesta válida."
    try:
        data = json.loads(clean_json)
        preds = data.get("predictions", [])
        if not preds:
            return "⚠️ El modelo devolvió un JSON sin predicciones."
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
            confidence = pred.get("confidence", None)
            conf_str = f" (confianza: {confidence}%)" if confidence is not None else ""
            score_str = f" ({score})" if score else ""
            display_game = game_names.get(game_key, game_key)
            lines.append(f"{i}. **{display_game}** → Favorito: **{fav}**{score_str}{conf_str}")
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
    return json.dumps({"ollama": ollama_ok, "binance": binance_ok, "espn": espn_ok})


def analyze_usage_history(history: list) -> str:
    """
    Analiza el historial de conversación y devuelve un resumen de uso.
    """
    if not history:
        return "No hay suficiente historial de uso para generar sugerencias personalizadas."

    # Contar tipos de interacciones
    usage_counter = Counter()
    topics = Counter()

    for msg in history:
        content = msg.get("content", "")
        role = msg.get("role", "")

        if role == "user":
            content_lower = content.lower()
            # Detectar marcadores especiales
            if "📰 noticias del día" in content_lower or "noticias" in content_lower:
                usage_counter["análisis de criptomonedas (noticias)"] += 1
                topics["criptomonedas"] += 1
            elif "₿ análisis" in content_lower or "bitcoin" in content_lower or "cripto" in content_lower:
                usage_counter["análisis individual de criptomonedas"] += 1
                topics["criptomonedas"] += 1
            elif "🏈" in content_lower or "deporte" in content_lower or "fútbol" in content_lower or "nba" in content_lower:
                usage_counter["predicciones deportivas"] += 1
                topics["deportes"] += 1
            elif "🎯 metas" in content_lower or "meta" in content_lower or "objetivo" in content_lower:
                usage_counter["gestión de metas"] += 1
                topics["productividad"] += 1
            elif "📄 informe" in content_lower or "semanal" in content_lower:
                usage_counter["informes semanales"] += 1
                topics["productividad"] += 1
            elif "📜 historial" in content_lower:
                usage_counter["consulta de historial"] += 1
            elif "tarea" in content_lower or "recordatorio" in content_lower:
                usage_counter["gestión de tareas"] += 1
                topics["productividad"] += 1
            elif "código" in content_lower or "python" in content_lower or "programar" in content_lower:
                usage_counter["programación Python"] += 1
                topics["desarrollo"] += 1
            else:
                usage_counter["consultas generales"] += 1

    # Construir resumen
    summary_lines = [
        "Resumen de uso del asistente:",
        f"- Total de interacciones analizadas: {len([m for m in history if m['role'] == 'user'])}",
    ]

    if usage_counter:
        summary_lines.append("\nFrecuencia de uso por funcionalidad:")
        for func, count in usage_counter.most_common(10):
            summary_lines.append(f"  - {func}: {count} veces")

    if topics:
        summary_lines.append("\nÁreas de interés principales:")
        for topic, count in topics.most_common(5):
            summary_lines.append(f"  - {topic}: {count} interacciones")

    summary_lines.append(f"\nÚltima interacción: {history[-1]['content'][:100]}...")

    return "\n".join(summary_lines)


def handle_client(conn, addr):
    try:
        raw_len = recv_exactly(conn, 4)
        (msg_len,) = struct.unpack("!I", raw_len)
        user_input = recv_exactly(conn, msg_len).decode("utf-8").strip()
        print(f"Pregunta recibida del avatar: {user_input}")

        history = load_recent_history(HISTORY_LIMIT)

        if user_input.startswith("__NEWS__"):
            coins_df = fetch_live_prices_for_news(limit=11)
            news_prompt = build_news_prompt(coins_df)
            response = direct_ollama_query(SYSTEM_PROMPT_NEWS, news_prompt, model=OLLAMA_TRADING_MODEL)
            save_message("user", "📰 Noticias del día")
            save_message("assistant", response)
            print(f"Respuesta (noticias): {response[:100]}...")

        elif user_input.startswith("__CRYPTO__"):
            parts = user_input.split(":", 1)
            symbol = parts[1].strip() if len(parts) > 1 else "BTCUSDT"
            if symbol == "ALL":
                resultados = []
                for sym in SELECTED_CRYPTO:
                    prompt = build_crypto_analysis_prompt(sym)
                    if prompt.startswith("Error"):
                        resultados.append(f"❌ {sym}: {prompt}")
                        continue
                    raw = direct_ollama_query(SYSTEM_PROMPT_CRYPTO, prompt, model=OLLAMA_TRADING_MODEL)
                    clean = _extract_first_json(raw)
                    if clean:
                        try:
                            pred_json = json.loads(clean)
                            direction = pred_json.get("direction", "desconocida")
                            target = pred_json.get("target_price", "N/D")
                            reasoning = pred_json.get("reasoning", "")
                            current_price = get_current_crypto_price(sym)
                            if current_price and direction in ("bullish", "bearish"):
                                save_crypto_prediction(sym, direction, target, current_price, raw)
                            resultados.append(f"**{sym}**: {direction.upper()} → objetivo ${target} ({reasoning[:80]}...)")
                        except Exception as e:
                            resultados.append(f"⚠️ {sym}: JSON inválido ({e})")
                    else:
                        resultados.append(f"⚠️ {sym}: sin JSON válido")
                    time.sleep(0.5)
                response = "₿ **Análisis de todas las criptomonedas**\n\n" + "\n\n".join(resultados)
            else:
                prompt = build_crypto_analysis_prompt(symbol)
                raw_response = direct_ollama_query(SYSTEM_PROMPT_CRYPTO, prompt, model=OLLAMA_TRADING_MODEL)
                clean_json = _extract_first_json(raw_response)
                if clean_json:
                    try:
                        pred_json = json.loads(clean_json)
                        direction = pred_json.get("direction", "").lower()
                        target_price = float(pred_json.get("target_price", 0))
                        current_price = get_current_crypto_price(symbol)
                        if direction in ("bullish", "bearish") and current_price:
                            save_crypto_prediction(symbol, direction, target_price, current_price, raw_response)
                    except Exception as e:
                        print(f"No se pudo guardar la predicción de {symbol}: {e}")
                try:
                    pred_json = json.loads(clean_json) if clean_json else json.loads(raw_response)
                    direction = pred_json.get("direction", "desconocida")
                    target = pred_json.get("target_price", "N/D")
                    reasoning = pred_json.get("reasoning", "")
                    response = f"₿ **Análisis {symbol}**\n\nDirección esperada: **{direction.upper()}**\nPrecio objetivo: ${target}\n\n{reasoning}"
                except:
                    response = raw_response
            save_message("user", "₿ Análisis cripto")
            save_message("assistant", response)
            print(f"Respuesta (cripto): {response[:100]}...")

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
                    print("No se pudo parsear la respuesta JSON del modelo.")
            else:
                print("No se encontró JSON válido en la respuesta deportiva.")
            formatted_response = format_sports_predictions(raw_response, games_data)
            save_message("user", f"🏈 Análisis deportivo ({category or 'todos'})")
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
                        norm_pred = normalize_text(predicted)
                        norm_real = normalize_text(real_winner)
                        if norm_pred and norm_real and norm_pred == norm_real:
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

            # Reporte cripto
            crypto_preds = get_all_crypto_predictions()
            response += "\n₿ **Predicciones de Criptomonedas**\n\n"
            if not crypto_preds:
                response += "No hay predicciones de criptomonedas todavía."
            else:
                cripto_stats = defaultdict(lambda: {"aciertos": 0, "fallos": 0, "pendientes": 0, "detalles": []})
                now = datetime.now()
                for cp in crypto_preds:
                    symbol = cp["symbol"]
                    if cp["checked"]:
                        if cp["result"] == "acierto":
                            cripto_stats[symbol]["aciertos"] += 1
                        else:
                            cripto_stats[symbol]["fallos"] += 1
                        continue
                    pred_time_str = cp["timestamp"]
                    try:
                        pred_time = datetime.fromisoformat(pred_time_str)
                    except:
                        pred_time = None
                    if pred_time and (now - pred_time) < timedelta(hours=24):
                        cripto_stats[symbol]["pendientes"] += 1
                        continue
                    current_price = get_current_crypto_price(symbol)
                    if current_price is None:
                        cripto_stats[symbol]["pendientes"] += 1
                        continue
                    predicted_direction = cp["direction"]
                    old_price = cp["current_price"]
                    if predicted_direction == "bullish" and current_price > old_price:
                        update_crypto_prediction_result(cp["id"], "acierto")
                        cripto_stats[symbol]["aciertos"] += 1
                    elif predicted_direction == "bearish" and current_price < old_price:
                        update_crypto_prediction_result(cp["id"], "acierto")
                        cripto_stats[symbol]["aciertos"] += 1
                    else:
                        update_crypto_prediction_result(cp["id"], "fallo")
                        cripto_stats[symbol]["fallos"] += 1
                for symbol, stats in sorted(cripto_stats.items()):
                    response += f"**{symbol}**: {stats['aciertos']} aciertos, {stats['fallos']} fallos"
                    if stats['pendientes'] > 0:
                        response += f", {stats['pendientes']} pendientes"
                    response += "\n"

        elif user_input.startswith("__GOALS__"):
            goals = list_goals(active_only=True)
            if not goals:
                response = "No tienes metas activas en este momento."
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

        elif user_input.startswith("__INCOME_IDEAS__"):
            # Cargar historial amplio para analizar patrones de uso
            full_history = load_recent_history(limit=100)
            usage_summary = analyze_usage_history(full_history)
            income_prompt = (
                f"A continuación se muestra un resumen del uso que el usuario ha hecho de su asistente virtual:\n\n"
                f"{usage_summary}\n\n"
                "Basándote en esta información, sugiere 3 maneras concretas de generar ingresos extra "
                "aprovechando las funcionalidades que más utiliza y sus áreas de interés. "
                "Sé específico, realista y motivador."
            )
            response = direct_ollama_query(SYSTEM_PROMPT_INCOME, income_prompt, model=OLLAMA_MODEL)
            save_message("user", "💡 Ideas de ingresos")
            save_message("assistant", response)
            print(f"Respuesta (ingresos): {response[:100]}...")

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
            subprocess.Popen([sys.executable, avatar_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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