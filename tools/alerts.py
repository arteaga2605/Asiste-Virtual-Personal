# tools/alerts.py
import time
import threading
import requests
import pandas as pd
from config import ALERT_FILE
from tools.trading import calculate_rsi, STABLECOINS

def _get_top_symbols(limit=20):
    """
    Obtiene los 'limit' símbolos USDT con mayor volumen en 24h,
    excluyendo stablecoins conocidas.
    Retorna una lista de strings con los símbolos.
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error obteniendo tickers (alertas): {e}")
        return []

    # Filtrar pares USDT y excluir stablecoins
    filtered = []
    for t in data:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base.upper() in STABLECOINS:
            continue
        quote_vol = t.get("quoteVolume")
        if quote_vol is not None:
            filtered.append((sym, float(quote_vol)))

    # Ordenar por volumen descendente y extraer símbolos
    filtered.sort(key=lambda x: x[1], reverse=True)
    symbols = [sym for sym, _ in filtered[:limit]]
    return symbols


def _get_rsi(symbol, interval="1h", limit=20):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        df = pd.DataFrame(resp.json(), columns=[
            "OpenTime", "Open", "High", "Low", "Close", "Volume",
            "CloseTime", "QuoteAssetVol", "NrTrades",
            "TakerBuyBaseVol", "TakerBuyQuoteVol", "Ignore"
        ])
        df["Close"] = pd.to_numeric(df["Close"], errors='coerce')
        rsi_series = calculate_rsi(df["Close"], 14)
        last_val = rsi_series.iloc[-1]
        if pd.isna(last_val):
            return None
        return round(float(last_val), 2)
    except Exception as e:
        print(f"Error calculando RSI para {symbol}: {e}")
        return None


def _get_24h_high_low(symbol):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    params = {"symbol": symbol}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        high = float(data["highPrice"])
        low = float(data["lowPrice"])
        return high, low
    except Exception as e:
        print(f"Error obteniendo high/low para {symbol}: {e}")
        return None, None


def start_alert_monitor(interval_minutes=5):
    """
    Hilo que verifica periódicamente condiciones de alerta y escribe en ALERT_FILE.
    """
    def monitor():
        while True:
            symbols = _get_top_symbols(20)
            for sym in symbols:
                rsi = _get_rsi(sym, "1h", 20)
                high, low = _get_24h_high_low(sym)
                price = None
                if high is not None and low is not None:
                    # Obtener último precio
                    try:
                        ticker_url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
                        resp = requests.get(ticker_url, timeout=5)
                        price = float(resp.json()["price"])
                    except Exception:
                        pass

                alerts = []
                if rsi is not None and rsi < 30:
                    alerts.append(f"RSI(1h) = {rsi} (<30)")
                if price is not None and high and low:
                    if price > high * 1.001:
                        alerts.append(f"Precio rompió máximo 24h: {price:.4f} > {high:.4f}")
                    elif price < low * 0.999:
                        alerts.append(f"Precio rompió mínimo 24h: {price:.4f} < {low:.4f}")

                if alerts:
                    msg = f"🚨 Alerta {sym}: " + ", ".join(alerts)
                    try:
                        with open(ALERT_FILE, "w", encoding="utf-8") as f:
                            f.write(msg)
                    except Exception:
                        pass
                time.sleep(0.5)  # pequeño descanso entre símbolos
            time.sleep(interval_minutes * 60)

    t = threading.Thread(target=monitor, daemon=True)
    t.start()