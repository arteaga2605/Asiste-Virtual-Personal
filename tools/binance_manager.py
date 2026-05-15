# tools/binance_manager.py
from datetime import datetime
from tools.trading import (
    fetch_live_prices_for_news, get_order_book_pressure, SELECTED_CRYPTO
)
from tools.business import get_binance_config, get_earn_expiring_soon, mark_earn_notified

def generate_business_suggestions() -> str | None:
    config = get_binance_config()
    capital = config["capital_total"]
    earn = config["earn_amount"]
    futures = config["futures_amount"]

    coins_df = fetch_live_prices_for_news(limit=12)
    if coins_df.empty:
        return None

    pressures = {}
    for sym in SELECTED_CRYPTO:
        pressures[sym] = get_order_book_pressure(sym)

    market_summary = []
    for _, row in coins_df.iterrows():
        sym = row["symbol"]
        rsi1h = row["rsi1h"] if row["rsi1h"] else "N/D"
        press = pressures.get(sym, "N/D")
        market_summary.append(f"- {sym}: ${row['lastPrice']:.4f} (24h: {row['priceChangePercent']:.2f}%), RSI 1h={rsi1h}, presión={press}")

    market_text = "\n".join(market_summary)

    # Verificar productos Earn próximos a vencer
    expiring = get_earn_expiring_soon(24)
    earn_reminder = ""
    if expiring:
        products = ", ".join([f"{p['symbol']} ({p['amount']} USDT, vence {p['release_date']})" for p in expiring])
        earn_reminder = f"⚠️ Productos Earn a punto de liberarse: {products}\n"
        for p in expiring:
            mark_earn_notified(p["id"])

    prompt = (
        "Eres un gestor profesional de criptomonedas en Binance. Tu cliente tiene un pequeño capital de "
        f"${capital:.2f}, distribuido en: Earn (ahorros) ${earn:.2f} y Futuros (trading) ${futures:.2f}.\n"
        f"{earn_reminder}"
        "Analiza los datos actuales del mercado y sugiere **una acción concreta** para maximizar ganancias "
        "o proteger el capital hoy. Puedes recomendar mover fondos entre Earn y Futuros, "
        "abrir una posición larga/corta, cambiar de moneda en Earn, etc. Sé breve y directo.\n\n"
        f"**Mercado actual**:\n{market_text}\n\n"
        "Responde solo con la recomendación, sin JSON ni herramientas."
    )
    return prompt

def generate_business_summary() -> str:
    config = get_binance_config()
    return (
        f"💼 **Resumen de tu negocio Binance**\n"
        f"💰 Capital total: ${config['capital_total']:.2f}\n"
        f"🏦 En Earn: ${config['earn_amount']:.2f}\n"
        f"📈 En Futuros: ${config['futures_amount']:.2f}\n\n"
        "Para cambiar estos valores, escribe en el chat: 'Configura mi negocio: capital X, earn Y, futuros Z'."
    )