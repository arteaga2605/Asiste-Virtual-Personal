# tools/alerts.py
import time
import threading
import requests
import pandas as pd
from config import ALERT_FILE
from tools.trading import calculate_rsi, calculate_sma, STABLECOINS


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

    filtered.sort(key=lambda x: x[1], reverse=True)
    symbols = [sym for sym, _ in filtered[:limit]]
    return symbols


def _get_klines(symbol, interval, limit):
    """Obtiene velas para un símbolo e intervalo dados."""
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
        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
        df["OpenTime"] = pd.to_datetime(df["OpenTime"], unit='ms')
        return df
    except Exception as e:
        print(f"Error obteniendo klines para {symbol} ({interval}): {e}")
        return pd.DataFrame()


def _get_rsi(symbol, interval, limit=20, period=14):
    """Calcula el RSI para un símbolo en un intervalo dado."""
    df = _get_klines(symbol, interval, limit)
    if df.empty or len(df) < period:
        return None
    rsi_series = calculate_rsi(df["Close"], period)
    last_val = rsi_series.iloc[-1]
    if pd.isna(last_val):
        return None
    return round(float(last_val), 2)


def _get_sma(symbol, interval, limit=30, period=9):
    """Calcula la SMA para un símbolo en un intervalo dado.
    Retorna el valor de la SMA y el precio de cierre actual."""
    df = _get_klines(symbol, interval, limit)
    if df.empty or len(df) < period:
        return None, None
    sma_series = calculate_sma(df["Close"], period)
    sma_val = sma_series.iloc[-1]
    close_val = df["Close"].iloc[-1]
    if pd.isna(sma_val) or pd.isna(close_val):
        return None, None
    return round(float(sma_val), 6), round(float(close_val), 6)


def _get_last_price(symbol):
    """Obtiene el último precio de un símbolo."""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=5)
        return float(resp.json()["price"])
    except:
        return None


def start_alert_monitor(interval_minutes=10):
    """
    Hilo que verifica periódicamente condiciones de alerta:
    - RSI 1 Semana y 1 Mes > 70 (sobrecompra) o < 30 (sobreventa)
    - Precio toca la SMA 9 en 4H, 1D, 1 Semana, 1 Mes
    Escribe las alertas en ALERT_FILE.
    """
    def monitor():
        while True:
            symbols = _get_top_symbols(20)
            for sym in symbols:
                alerts = []

                # --- RSI 1 Semana (>70 o <30) ---
                rsi_1w = _get_rsi(sym, "1w", limit=20, period=14)
                if rsi_1w is not None:
                    if rsi_1w > 70:
                        alerts.append(f"RSI 1Semana = {rsi_1w} (sobrecompra >70)")
                    elif rsi_1w < 30:
                        alerts.append(f"RSI 1Semana = {rsi_1w} (sobreventa <30)")

                # --- RSI 1 Mes (>70 o <30) ---
                rsi_1M = _get_rsi(sym, "1M", limit=20, period=14)
                if rsi_1M is not None:
                    if rsi_1M > 70:
                        alerts.append(f"RSI 1Mes = {rsi_1M} (sobrecompra >70)")
                    elif rsi_1M < 30:
                        alerts.append(f"RSI 1Mes = {rsi_1M} (sobreventa <30)")

                # --- SMA 9 en 4H, 1D, 1S, 1M (precio toca la SMA) ---
                for interval, label in [("4h", "4H"), ("1d", "1D"), ("1w", "1Sem"), ("1M", "1Mes")]:
                    sma_val, close_val = _get_sma(sym, interval, limit=30, period=9)
                    if sma_val is not None and close_val is not None:
                        # Consideramos "tocar" si la diferencia es < 0.5%
                        if sma_val > 0:
                            diff_pct = abs(close_val - sma_val) / sma_val
                            if diff_pct < 0.005:  # menos del 0.5%
                                if close_val >= sma_val:
                                    alerts.append(f"Precio tocó SMA9 {label} (${sma_val:.6f}) al alza")
                                else:
                                    alerts.append(f"Precio tocó SMA9 {label} (${sma_val:.6f}) a la baja")

                if alerts:
                    msg = f"🚨 Alerta {sym}: " + " | ".join(alerts)
                    try:
                        with open(ALERT_FILE, "w", encoding="utf-8") as f:
                            f.write(msg)
                    except Exception:
                        pass

                time.sleep(0.3)  # pequeño descanso entre símbolos

            time.sleep(interval_minutes * 60)

    t = threading.Thread(target=monitor, daemon=True)
    t.start()