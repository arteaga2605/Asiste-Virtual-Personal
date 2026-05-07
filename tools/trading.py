# tools/trading.py
import pandas as pd
import numpy as np
import json
import threading
import time
import websocket
import requests
from config import DATA_DIR, BINANCE_WS_URL

# ------------------------------------------------------------
# Funciones ya existentes (mantenidas sin cambios)
# ------------------------------------------------------------
def load_historical_data(symbol: str) -> pd.DataFrame:
    filepath = f"{DATA_DIR}/{symbol.upper()}.csv"
    df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
    return df

def get_symbol_data(symbol: str, start: str = None, end: str = None) -> dict:
    try:
        df = load_historical_data(symbol)
        if start:
            df = df.loc[start:]
        if end:
            df = df.loc[:end]
        last_close = df['Close'].iloc[-1]
        max_price = df['High'].max()
        min_price = df['Low'].min()
        return {
            "symbol": symbol.upper(),
            "last_close": last_close,
            "max": max_price,
            "min": min_price,
            "data_points": len(df)
        }
    except Exception as e:
        return {"error": str(e)}

def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({
        'MACD': macd_line,
        'MACD_signal': signal_line,
        'MACD_hist': histogram
    })

def calculate_indicator(symbol: str, indicator: str, period: int = 14) -> dict:
    try:
        df = load_historical_data(symbol)
        close = df['Close']
        if indicator.lower() == 'rsi':
            result_series = calculate_rsi(close, period)
            col = f"RSI_{period}"
        elif indicator.lower() == 'sma':
            result_series = calculate_sma(close, period)
            col = f"SMA_{period}"
        elif indicator.lower() == 'ema':
            result_series = calculate_ema(close, period)
            col = f"EMA_{period}"
        elif indicator.lower() == 'macd':
            macd_df = calculate_macd(close)
            result_series = macd_df['MACD']
            col = "MACD"
        else:
            return {"error": f"Indicador {indicator} no soportado"}
        last_value = result_series.iloc[-1]
        if pd.isna(last_value):
            last_value = None
        return {
            "symbol": symbol.upper(),
            "indicator": indicator.upper(),
            "period": period,
            "last_value": last_value
        }
    except Exception as e:
        return {"error": str(e)}

# ------------------------------------------------------------
# WebSocket de Binance (moderado en errores)
# ------------------------------------------------------------
_live_prices = {}
_error_count = 0

def _on_message(ws, message):
    data = json.loads(message)
    symbol = data.get('s', '').upper()
    price = float(data.get('c', 0))
    _live_prices[symbol] = price

def _on_error(ws, error):
    global _error_count
    _error_count += 1
    if _error_count % 10 == 1:
        print(f"WebSocket error: {error} (ocultos {_error_count-1} errores similares)")

def _on_close(ws, close_status_code, close_msg):
    global _error_count
    _error_count += 1
    if _error_count % 10 == 1:
        print("WebSocket cerrado, reintentando...")
    time.sleep(5)

def start_binance_stream(symbols: list):
    streams = "/".join([f"{s.lower()}@miniTicker" for s in symbols])
    ws_url = f"{BINANCE_WS_URL}/{streams}"
    def run_ws():
        while True:
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close
            )
            ws.run_forever()
            time.sleep(10)
    thread = threading.Thread(target=run_ws, daemon=True)
    thread.start()
    return f"Stream iniciado para {symbols}"

def get_live_price(symbol: str) -> float:
    return _live_prices.get(symbol.upper(), None)

# ------------------------------------------------------------
# NUEVAS FUNCIONES PARA "NOTICIAS DEL DÍA" (joyas cripto)
# ------------------------------------------------------------
def _get_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Descarga velas de un par USDT y devuelve DataFrame con columnas estándar."""
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            "OpenTime", "Open", "High", "Low", "Close", "Volume",
            "CloseTime", "QuoteAssetVol", "NrTrades",
            "TakerBuyBaseVol", "TakerBuyQuoteVol", "Ignore"
        ])
        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
        df["OpenTime"] = pd.to_datetime(df["OpenTime"], unit='ms')
        return df
    except Exception as e:
        print(f"Error descargando klines para {symbol} ({interval}): {e}")
        return pd.DataFrame()

# Lista de stablecoins conocidas para excluir
STABLECOINS = {
    "USDC", "BUSD", "TUSD", "USDP", "USDD", "DAI", "FRAX", "LUSD", "USDJ",
    "USTC", "USDS", "FDUSD", "UST", "PAX", "GUSD", "USDX", "CUSD"
}

def _get_rsi_for_timeframe(symbol: str, interval: str, limit: int, period: int = 14) -> float | None:
    """Obtiene el RSI(period) para un símbolo usando velas de 'interval'."""
    df = _get_klines(symbol, interval, limit)
    if df.empty or len(df) < period:
        return None
    rsi_series = calculate_rsi(df["Close"], period)
    last_val = rsi_series.iloc[-1]
    if pd.isna(last_val):
        return None
    return round(float(last_val), 2)

def fetch_live_prices_for_news(limit: int = 50) -> pd.DataFrame:
    """
    Obtiene las 'limit' monedas con mayor volumen USDT (excluyendo stablecoins),
    y calcula RSI para 1h, 4h y 1d.
    Retorna un DataFrame con columnas: symbol, lastPrice, priceChangePercent,
    volume, rsi1h, rsi4h, rsi1d.
    """
    ticker_url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = requests.get(ticker_url, timeout=15)
        resp.raise_for_status()
        all_tickers = resp.json()
    except Exception as e:
        print(f"Error descargando tickers: {e}")
        return pd.DataFrame()

    usdt_tickers = []
    for t in all_tickers:
        sym = t["symbol"]
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base.upper() in STABLECOINS:
            continue
        if t.get("quoteVolume"):
            usdt_tickers.append(t)

    usdt_tickers.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
    top = usdt_tickers[:limit]

    data_rows = []
    for ticker in top:
        sym = ticker["symbol"]
        last_price = float(ticker["lastPrice"])
        pct_change = float(ticker["priceChangePercent"])
        volume = float(ticker["quoteVolume"])

        # RSI multi‑timeframe
        rsi1h = _get_rsi_for_timeframe(sym, "1h", 20, 14)
        rsi4h = _get_rsi_for_timeframe(sym, "4h", 20, 14)
        rsi1d = _get_rsi_for_timeframe(sym, "1d", 20, 14)

        data_rows.append({
            "symbol": sym,
            "lastPrice": last_price,
            "priceChangePercent": pct_change,
            "volume": volume,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,
            "rsi1d": rsi1d
        })
        time.sleep(0.1)  # pequeño delay para respetar límites de la API

    return pd.DataFrame(data_rows)


def build_news_prompt(coins_df: pd.DataFrame) -> str:
    """Construye el prompt para el LLM con datos multi‑timeframe."""
    if coins_df.empty:
        return "No se pudieron obtener datos de monedas en este momento."

    display_df = coins_df.head(30)

    lines = []
    for _, row in display_df.iterrows():
        rsi1h_str = f"{row['rsi1h']}" if pd.notna(row["rsi1h"]) else "N/D"
        rsi4h_str = f"{row['rsi4h']}" if pd.notna(row["rsi4h"]) else "N/D"
        rsi1d_str = f"{row['rsi1d']}" if pd.notna(row["rsi1d"]) else "N/D"
        line = (f"- {row['symbol']}: ${row['lastPrice']:.4f}, "
                f"24h: {row['priceChangePercent']:.2f}%, "
                f"Vol: {row['volume']:.0f} USDT, "
                f"RSI(1h)={rsi1h_str}, RSI(4h)={rsi4h_str}, RSI(1d)={rsi1d_str}")
        lines.append(line)

    coins_summary = "\n".join(lines)

    prompt = (
        "Eres un analista experto en criptomonedas. A continuación tienes los datos actuales "
        f"de {len(display_df)} criptomonedas (pares USDT) obtenidos en tiempo real desde Binance. "
        "Se incluye precio, cambio 24h, volumen y RSI de 14 periodos en tres marcos de tiempo: "
        "1 hora, 4 horas y 1 día.\n\n"
        f"{coins_summary}\n\n"
        "**Tarea**: encuentra 3 criptomonedas que consideres 'joyas ocultas' para invertir "
        "a un plazo de 1 día. Para hacerlo, ten en cuenta todo el espectro temporal:\n"
        "- Busca monedas con RSI bajo (<30) en cualquiera de los plazos, especialmente si coincide en varios.\n"
        "- El volumen alto es una señal de interés real del mercado.\n"
        "- Explica por qué cada una podría estar infravalorada y por qué puede rebotar.\n"
        "- Responde solo con texto, sin herramientas ni funciones. Sé conciso."
    )
    return prompt