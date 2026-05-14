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
# Funciones ya existentes (sin cambios)
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
_stream_active = False

def _on_message(ws, message):
    data = json.loads(message)
    symbol = data.get('s', '').upper()
    price = float(data.get('c', 0))
    _live_prices[symbol] = price

def _on_error(ws, error):
    global _error_count, _stream_active
    _error_count += 1
    if _error_count % 10 == 1:
        print(f"WebSocket error: {error} (ocultos {_error_count-1} errores similares)")
    _stream_active = False

def _on_close(ws, close_status_code, close_msg):
    global _error_count, _stream_active
    _error_count += 1
    if _error_count % 10 == 1:
        print("WebSocket cerrado, reintentando...")
    _stream_active = False
    time.sleep(5)

def _on_open(ws):
    global _stream_active
    _stream_active = True

def start_binance_stream(symbols: list):
    streams = "/".join([f"{s.lower()}@miniTicker" for s in symbols])
    ws_url = f"{BINANCE_WS_URL}/{streams}"
    def run_ws():
        while True:
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
                on_open=_on_open
            )
            ws.run_forever()
            time.sleep(10)
    thread = threading.Thread(target=run_ws, daemon=True)
    thread.start()
    return f"Stream iniciado para {symbols}"

def get_live_price(symbol: str) -> float:
    return _live_prices.get(symbol.upper(), None)

def is_binance_stream_active() -> bool:
    return _stream_active

# ------------------------------------------------------------
# LISTA FIJA DE CRIPTOMONEDAS (ahora con DASH)
# ------------------------------------------------------------
SELECTED_CRYPTO = [
    "BTCUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT",
    "TRXUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT",
    "DOTUSDT", "AVAXUSDT", "UNIUSDT", "DASHUSDT"
]

def _get_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
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


def _get_rsi_for_timeframe(symbol: str, interval: str, limit: int, period: int = 14) -> float | None:
    df = _get_klines(symbol, interval, limit)
    if df.empty or len(df) < period:
        return None
    rsi_series = calculate_rsi(df["Close"], period)
    last_val = rsi_series.iloc[-1]
    if pd.isna(last_val):
        return None
    return round(float(last_val), 2)


def get_order_book_pressure(symbol: str) -> float | None:
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": symbol, "limit": 100}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        total_bids = sum(float(b[1]) for b in bids)
        total_asks = sum(float(a[1]) for a in asks)
        if total_asks == 0:
            return None
        return round(total_bids / total_asks, 4)
    except Exception as e:
        print(f"Error obteniendo order book para {symbol}: {e}")
        return None


def fetch_live_prices_for_news(limit: int = 20) -> pd.DataFrame:
    ticker_url = "https://api.binance.com/api/v3/ticker/24hr"
    all_tickers = []
    try:
        resp = requests.get(ticker_url, timeout=15)
        resp.raise_for_status()
        all_tickers = resp.json()
    except Exception as e:
        print(f"Error descargando tickers: {e}")
        return pd.DataFrame()

    ticker_map = {}
    for t in all_tickers:
        sym = t["symbol"]
        if sym in SELECTED_CRYPTO:
            ticker_map[sym] = t

    data_rows = []
    for sym in SELECTED_CRYPTO:
        if sym not in ticker_map:
            continue
        ticker = ticker_map[sym]
        last_price = float(ticker["lastPrice"])
        pct_change = float(ticker["priceChangePercent"])
        volume = float(ticker["quoteVolume"])

        rsi1h = _get_rsi_for_timeframe(sym, "1h", 20, 14)
        rsi4h = _get_rsi_for_timeframe(sym, "4h", 20, 14)
        rsi1d = _get_rsi_for_timeframe(sym, "1d", 20, 14)
        pressure = get_order_book_pressure(sym)

        data_rows.append({
            "symbol": sym,
            "lastPrice": last_price,
            "priceChangePercent": pct_change,
            "volume": volume,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,
            "rsi1d": rsi1d,
            "buyPressure": pressure
        })
        time.sleep(0.15)

    return pd.DataFrame(data_rows)


def build_news_prompt(coins_df: pd.DataFrame) -> str:
    if coins_df.empty:
        return "No se pudieron obtener datos de las criptomonedas seleccionadas."

    lines = []
    for _, row in coins_df.iterrows():
        rsi1h_str = f"{row['rsi1h']}" if pd.notna(row["rsi1h"]) else "N/D"
        rsi4h_str = f"{row['rsi4h']}" if pd.notna(row["rsi4h"]) else "N/D"
        rsi1d_str = f"{row['rsi1d']}" if pd.notna(row["rsi1d"]) else "N/D"
        press_str = f"{row['buyPressure']}" if pd.notna(row.get("buyPressure")) else "N/D"
        line = (f"- {row['symbol']}: ${row['lastPrice']:.4f}, "
                f"24h: {row['priceChangePercent']:.2f}%, "
                f"Vol: {row['volume']:.0f} USDT, "
                f"RSI(1h)={rsi1h_str}, RSI(4h)={rsi4h_str}, RSI(1d)={rsi1d_str}, "
                f"Presión compra: {press_str}")
        lines.append(line)

    coins_summary = "\n".join(lines)

    prompt = (
        "Eres un analista experto en criptomonedas. A continuación tienes los datos actuales "
        f"de las criptomonedas seleccionadas (pares USDT) obtenidos en tiempo real desde Binance. "
        "Se incluye precio, cambio 24h, volumen, RSI de 14 periodos en tres marcos de tiempo "
        "(1h, 4h, 1d) y la presión compradora (ratio bids/asks del libro de órdenes, >1 indica más compras).\n\n"
        f"{coins_summary}\n\n"
        "**Tarea**: encuentra 3 criptomonedas que consideres 'joyas ocultas' para invertir "
        "a un plazo de 1 día. Para hacerlo, ten en cuenta todo el espectro temporal:\n"
        "- Busca monedas con RSI bajo (<30) en cualquiera de los plazos, especialmente si coincide en varios.\n"
        "- El volumen alto es una señal de interés real del mercado.\n"
        "- Una presión compradora alta sugiere que el mercado está inclinado al alza.\n"
        "- Explica por qué cada una podría estar infravalorada y por qué puede rebotar.\n"
        "- Responde solo con texto, sin herramientas ni funciones. Sé conciso."
    )
    return prompt

# ------------------------------------------------------------
# NUEVAS FUNCIONES PARA ANÁLISIS TÉCNICO DE CRIPTOMONEDAS
# ------------------------------------------------------------

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['High']
    low = df['Low']
    close = df['Close'].shift(1)
    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr


def calculate_fibonacci_levels(df: pd.DataFrame) -> dict:
    if len(df) < 20:
        return {}
    high = df['High'].max()
    low = df['Low'].min()
    last_price = df['Close'].iloc[-1]
    diff = high - low
    fib_50 = low + diff * 0.5
    fib_618 = low + diff * 0.618
    role_50 = "soporte" if last_price > fib_50 else "resistencia"
    role_618 = "soporte" if last_price > fib_618 else "resistencia"
    return {
        "ultimo_swing_high": high,
        "ultimo_swing_low": low,
        "precio_actual": last_price,
        "fib_50": fib_50,
        "rol_50": role_50,
        "fib_618": fib_618,
        "rol_618": role_618
    }


def detect_candle_patterns(df: pd.DataFrame) -> list:
    patterns = []
    if len(df) < 3:
        return patterns
    recent = df.tail(5).copy()
    for i in range(len(recent) - 1, 0, -1):
        open_ = recent.iloc[i]['Open']
        close_ = recent.iloc[i]['Close']
        high_ = recent.iloc[i]['High']
        low_ = recent.iloc[i]['Low']
        body = abs(close_ - open_)
        lower_shadow = min(open_, close_) - low_
        upper_shadow = high_ - max(open_, close_)
        if lower_shadow > body * 2 and upper_shadow < body * 0.5 and close_ > open_:
            patterns.append("Martillo alcista")
        if upper_shadow > body * 2 and lower_shadow < body * 0.5 and close_ < open_:
            patterns.append("Estrella fugaz")
        if body < (high_ - low_) * 0.1:
            patterns.append("Doji")
        if i > 0:
            prev_open = recent.iloc[i-1]['Open']
            prev_close = recent.iloc[i-1]['Close']
            prev_body = abs(prev_close - prev_open)
            if close_ > open_ and prev_close < prev_open and body > prev_body and close_ > prev_open and open_ < prev_close:
                patterns.append("Envolvente alcista")
            elif close_ < open_ and prev_close > prev_open and body > prev_body and close_ < prev_open and open_ > prev_close:
                patterns.append("Envolvente bajista")
    return patterns


def get_current_crypto_price(symbol: str) -> float | None:
    """Obtiene el último precio de un símbolo desde la API de Binance."""
    try:
        resp = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        print(f"Error obteniendo precio {symbol}: {e}")
        return None


def build_crypto_analysis_prompt(symbol: str = "BTCUSDT") -> str:
    """
    Obtiene datos de un par USDT (diario, 90 velas), calcula indicadores y construye un prompt
    que solicita una respuesta JSON estructurada con la predicción.
    """
    INTERVAL = "1d"
    LIMIT = 90

    df = _get_klines(symbol, INTERVAL, LIMIT)
    if df.empty:
        return f"Error al obtener datos de {symbol}. Intenta de nuevo más tarde."

    close = df['Close']
    last_price = close.iloc[-1]
    high_90 = df['High'].max()
    low_90 = df['Low'].min()

    rsi_diario = _get_rsi_for_timeframe(symbol, "1d", LIMIT, period=14)

    atr_series = calculate_atr(df, period=14)
    current_atr = atr_series.iloc[-1]

    avg_vol = df['Volume'].tail(20).mean()
    last_vol = df['Volume'].iloc[-1]

    fib_levels = calculate_fibonacci_levels(df)

    df_1m = df.tail(30)
    df_1w = df.tail(7)
    resistencias_1m = df_1m['High'].nlargest(3).tolist()
    soportes_1m = df_1m['Low'].nsmallest(3).tolist()
    resistencias_1w = df_1w['High'].nlargest(2).tolist()
    soportes_1w = df_1w['Low'].nsmallest(2).tolist()

    patterns = detect_candle_patterns(df)
    patterns_str = ", ".join(patterns) if patterns else "Ninguno detectado"

    prompt = (
        f"Eres un analista técnico experto en {symbol}. Analiza los siguientes datos y devuelve "
        "**exclusivamente** un JSON (sin texto adicional) con tu predicción para el corto plazo (próximos días).\n"
        "El JSON debe tener esta estructura exacta:\n"
        '{"direction": "bullish" o "bearish", "target_price": número, "reasoning": "breve explicación"}\n\n'
        f"**Precio actual**: ${last_price:.2f}\n"
        f"**Máximo 3 meses**: ${high_90:.2f}\n"
        f"**Mínimo 3 meses**: ${low_90:.2f}\n"
        f"**RSI diario (14)**: {rsi_diario if rsi_diario else 'N/D'}\n"
        f"**ATR (14)**: ${current_atr:.2f}\n"
        f"**Volumen última vela**: {last_vol:.2f} (media 20d: {avg_vol:.2f})\n\n"
        "**Soportes y resistencias**:\n"
        f"  - Último mes: Resistencias {resistencias_1m}, Soportes {soportes_1m}\n"
        f"  - Última semana: Resistencias {resistencias_1w}, Soportes {soportes_1w}\n\n"
        "**Niveles de Fibonacci** (desde el último swing):\n"
        f"  - Swing alto: ${fib_levels.get('ultimo_swing_high', 'N/A'):.2f}\n"
        f"  - Swing bajo: ${fib_levels.get('ultimo_swing_low', 'N/A'):.2f}\n"
        f"  - 0.50: ${fib_levels.get('fib_50', 'N/A'):.2f} → actuando como {fib_levels.get('rol_50', 'desconocido')}\n"
        f"  - 0.618: ${fib_levels.get('fib_618', 'N/A'):.2f} → actuando como {fib_levels.get('rol_618', 'desconocido')}\n\n"
        f"**Patrones de velas recientes**: {patterns_str}\n\n"
        "Proporciona el JSON con tu predicción."
    )
    return prompt