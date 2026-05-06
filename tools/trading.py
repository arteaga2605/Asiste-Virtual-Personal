# tools/trading.py
import pandas as pd
import numpy as np
import json
import threading
import time
import websocket
from config import DATA_DIR, BINANCE_WS_URL

# ------------------- DATOS HISTÓRICOS -------------------
def load_historical_data(symbol: str) -> pd.DataFrame:
    """
    Carga datos históricos desde un CSV ubicado en DATA_DIR/symbol.csv.
    Espera columnas: Date, Open, High, Low, Close, Volume
    """
    filepath = f"{DATA_DIR}/{symbol.upper()}.csv"
    df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
    return df

def get_symbol_data(symbol: str, start: str = None, end: str = None) -> dict:
    """
    Devuelve información resumida de un activo en un periodo.
    """
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

# ------------------- INDICADORES MANUALES -------------------
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
    """
    Calcula un indicador técnico sobre los datos históricos.
    Indicadores soportados: 'rsi', 'sma', 'ema', 'macd'
    """
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

# ------------------- DATOS EN TIEMPO REAL (Binance WebSocket) -------------------

_live_prices = {}
_error_count = 0  # contador para no saturar la consola

def _on_message(ws, message):
    data = json.loads(message)
    symbol = data.get('s', '').upper()
    price = float(data.get('c', 0))
    _live_prices[symbol] = price

def _on_error(ws, error):
    global _error_count
    _error_count += 1
    if _error_count % 10 == 1:  # mostrar solo 1 de cada 10 errores
        print(f"WebSocket error: {error} (ocultos {_error_count-1} errores similares)")

def _on_close(ws, close_status_code, close_msg):
    global _error_count
    _error_count += 1
    if _error_count % 10 == 1:
        print("WebSocket cerrado, reintentando...")
    time.sleep(5)

def start_binance_stream(symbols: list):
    """
    Inicia un hilo con conexión WebSocket a Binance y reconexión automática.
    """
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
    """Devuelve el último precio conocido de un símbolo."""
    return _live_prices.get(symbol.upper(), None)

# ------------------- BACKTESTING SIMPLE -------------------
def run_backtest(symbol: str, strategy_code: str) -> dict:
    """
    Ejecuta un backtest definido por código Python (se conecta con code_executor).
    """
    pass