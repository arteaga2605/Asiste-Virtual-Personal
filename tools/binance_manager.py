# tools/binance_manager.py
import json
import requests
from datetime import datetime
from tools.trading import (
    fetch_live_prices_for_news, get_current_crypto_price, SELECTED_CRYPTO,
    calculate_rsi, _get_klines, get_order_book_pressure
)
from tools.business import get_binance_config

def _get_earn_products() -> list:
    """
    Obtiene productos de Earn flexibles de Binance (requiere API key con permiso de lectura).
    Si no está configurada, devuelve una lista vacía.
    """
    return []  # por simplicidad, no usaremos datos reales de Earn en esta versión

def generate_business_suggestions() -> str | None:
    """
    Genera sugerencias automáticas para el negocio de Binance.
    Retorna un texto con recomendaciones o None si no hay nada relevante.
    """
    config = get_binance_config()
    capital = config["capital_total"]
    earn = config["earn_amount"]
    futures = config["futures_amount"]

    # Obtener datos de mercado de las criptos seleccionadas
    coins_df = fetch_live_prices_for_news(limit=12)
    if coins_df.empty:
        return None

    # Calcular presión compradora para todas
    pressures = {}
    for sym in SELECTED_CRYPTO:
        pressures[sym] = get_order_book_pressure(sym)

    # Construir resumen de mercado
    market_summary = []
    for _, row in coins_df.iterrows():
        sym = row["symbol"]
        rsi1h = row["rsi1h"] if row["rsi1h"] else "N/D"
        press = pressures.get(sym, "N/D")
        market_summary.append(f"- {sym}: ${row['lastPrice']:.4f} (24h: {row['priceChangePercent']:.2f}%), RSI 1h={rsi1h}, presión={press}")

    market_text = "\n".join(market_summary)

    prompt = (
        "Eres un gestor profesional de criptomonedas en Binance. Tu cliente tiene un pequeño capital de "
        f"${capital:.2f}, distribuido en: Earn (ahorros) ${earn:.2f} y Futuros (trading) ${futures:.2f}.\n"
        "Analiza los datos actuales del mercado y sugiere **una acción concreta** para maximizar ganancias "
        "o proteger el capital hoy. Puedes recomendar mover fondos entre Earn y Futuros, "
        "abrir una posición larga/corta, cambiar de moneda en Earn, etc. Sé breve y directo.\n\n"
        f"**Mercado actual**:\n{market_text}\n\n"
        "Responde solo con la recomendación, sin JSON ni herramientas."
    )
    return prompt  # Se procesará en main.py con llama3.1

def generate_business_summary() -> str:
    """Devuelve un resumen actual del negocio para mostrar en el chat."""
    config = get_binance_config()
    return (
        f"💼 **Resumen de tu negocio Binance**\n"
        f"💰 Capital total: ${config['capital_total']:.2f}\n"
        f"🏦 En Earn: ${config['earn_amount']:.2f}\n"
        f"📈 En Futuros: ${config['futures_amount']:.2f}\n\n"
        "Para cambiar estos valores, escribe en el chat: 'Configura mi negocio: capital X, earn Y, futuros Z'."
    )