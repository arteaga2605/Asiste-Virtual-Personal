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
def _get_klines(symbol: str, interval: str = "1h", limit: int = 20) -> pd.DataFrame:
    """Descarga velas recientes de un par USDT y devuelve un DataFrame con columnas estándar."""
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
        print(f"Error descargando klines para {symbol}: {e}")
        return pd.DataFrame()

# Lista de stablecoins conocidas (sin USDT base)
STABLECOINS = {
    "USDC", "BUSD", "TUSD", "USDP", "USDD", "DAI", "FRAX", "LUSD", "USDJ",
    "USTC", "USDS", "FDUSD", "UST", "PAX", "GUSD", "USDX", "CUSD"
}

def fetch_live_prices_for_news(limit: int = 50) -> pd.DataFrame:
    """
    Amplía el universo de monedas:
    - Obtiene todos los tickers de USDT de Binance (/api/v3/ticker/24hr).
    - Filtra solo pares que terminan en USDT.
    - Excluye stablecoins conocidas.
    - Ordena por volumen cotizado (quoteVolume) descendente y toma los primeros 'limit'.
    - Para cada uno descarga 15 velas de 1h y calcula RSI(14) sobre el cierre.
    - Devuelve un DataFrame con columnas: symbol, lastPrice, priceChangePercent, volume, rsi.
    """
    ticker_url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = requests.get(ticker_url, timeout=15)
        resp.raise_for_status()
        all_tickers = resp.json()
    except Exception as e:
        print(f"Error descargando tickers: {e}")
        return pd.DataFrame()

    # Filtrar pares USDT y excluir stablecoins
    usdt_tickers = []
    for t in all_tickers:
        sym = t["symbol"]
        if not sym.endswith("USDT"):
            continue
        # Extraer la moneda base (sin el USDT)
        base = sym[:-4]  # quita "USDT"
        if base.upper() in STABLECOINS:
            continue  # saltar stablecoins
        if t.get("quoteVolume"):
            usdt_tickers.append(t)

    usdt_tickers.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
    top = usdt_tickers[:limit]

    data_rows = []
    for ticker in top:
        sym = ticker["symbol"]
        last_price = float(ticker["lastPrice"])
        pct_change = float(ticker["priceChangePercent"])
        volume = float(ticker["quoteVolume"])  # volumen en USDT

        # Obtener velas 1h y calcular RSI
        klines = _get_klines(sym, interval="1h", limit=15)
        rsi_val = None
        if not klines.empty and len(klines) >= 14:
            close_series = klines["Close"]
            rsi_series = calculate_rsi(close_series, 14)
            last_rsi = rsi_series.iloc[-1]
            if not pd.isna(last_rsi):
                rsi_val = round(float(last_rsi), 2)
        data_rows.append({
            "symbol": sym,
            "lastPrice": last_price,
            "priceChangePercent": pct_change,
            "volume": volume,
            "rsi14": rsi_val
        })
        time.sleep(0.05)  # pequeño delay para no saturar la API

    return pd.DataFrame(data_rows)


def build_news_prompt(coins_df: pd.DataFrame) -> str:
    """
    Construye un prompt detallado con los datos de las 50 monedas y las instrucciones
    para encontrar joyas ocultas (RSI bajo, volumen alto, explicar infravaloración).
    """
    if coins_df.empty:
        return "No se pudieron obtener datos de monedas en este momento."

    # Para que el prompt no sea excesivo, limitamos a las 30 primeras
    display_df = coins_df.head(30)

    # Crear líneas por cada moneda
    lines = []
    for _, row in display_df.iterrows():
        rsi_str = f"{row['rsi14']}" if pd.notna(row["rsi14"]) else "N/D"
        line = (f"- {row['symbol']}: ${row['lastPrice']:.4f}, "
                f"24h: {row['priceChangePercent']:.2f}%, "
                f"Volumen: {row['volume']:.0f} USDT, "
                f"RSI(14): {rsi_str}")
        lines.append(line)

    coins_summary = "\n".join(lines)

    prompt = (
        "Eres un analista experto en criptomonedas. A continuación tienes los datos actuales "
        f"de {len(display_df)} criptomonedas (pares USDT) obtenidos en tiempo real desde Binance. "
        "Se incluye el precio, cambio porcentual en 24h, volumen y el RSI de 14 periodos.\n\n"
        f"{coins_summary}\n\n"
        "**Tarea**: encuentra 3 criptomonedas que consideres 'joyas ocultas' para invertir "
        "a un plazo de 1 día. Para hacerlo, ten en cuenta lo siguiente:\n"
        "- Busca monedas con RSI(14) por debajo de 30 (sobrevendidas) y volumen alto.\n"
        "- Explica por qué cada una podría estar infravalorada y por qué puede rebotar.\n"
        "- Responde solo con texto, sin herramientas ni funciones. Sé conciso."
    )
    return prompt