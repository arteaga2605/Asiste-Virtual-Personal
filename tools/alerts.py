# tools/alerts.py
import time
import threading
import requests
import pandas as pd
from config import ALERT_FILE
from tools.trading import calculate_rsi, calculate_sma, SELECTED_CRYPTO


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
    """Calcula la SMA y el precio de cierre actual para un símbolo."""
    df = _get_klines(symbol, interval, limit)
    if df.empty or len(df) < period:
        return None, None
    sma_series = calculate_sma(df["Close"], period)
    sma_val = sma_series.iloc[-1]
    close_val = df["Close"].iloc[-1]
    if pd.isna(sma_val) or pd.isna(close_val):
        return None, None
    return round(float(sma_val), 6), round(float(close_val), 6)


def start_alert_monitor(interval_minutes=10):
    """
    Hilo que verifica periódicamente condiciones de alerta para los 10 símbolos fijos.
    """
    def monitor():
        while True:
            symbols = SELECTED_CRYPTO
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

                time.sleep(0.3)

            time.sleep(interval_minutes * 60)

    t = threading.Thread(target=monitor, daemon=True)
    t.start()