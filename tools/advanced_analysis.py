# tools/advanced_analysis.py
import numpy as np
import pandas as pd
import requests
import time
from tools.trading import _get_klines, calculate_atr, STABLECOINS

def _hurst(ts: pd.Series) -> float:
    ts = ts.dropna().values
    if len(ts) < 30:
        return 0.5
    lags = range(10, min(len(ts)//2, 200))
    tau = []
    for lag in lags:
        n_slices = len(ts) // lag
        if n_slices < 2:
            continue
        rs = []
        for i in range(n_slices):
            chunk = ts[i*lag : (i+1)*lag]
            mean = np.mean(chunk)
            dev = chunk - mean
            cumdev = np.cumsum(dev)
            r = np.max(cumdev) - np.min(cumdev)
            s = np.std(chunk)
            if s > 0:
                rs.append(r/s)
        if rs:
            tau.append((lag, np.mean(rs)))
    if len(tau) < 4:
        return 0.5
    x = np.log([t[0] for t in tau])
    y = np.log([t[1] for t in tau])
    coeffs = np.polyfit(x, y, 1)
    return coeffs[0]

def _arima_forecast(ts: pd.Series, horizon: int = 1) -> tuple[float | None, str | None]:
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:
        return None, "statsmodels no está instalado. Ejecuta 'pip install statsmodels'"
    ts_clean = ts.dropna()
    if len(ts_clean) < 30:
        return None, f"Datos insuficientes para ARIMA (solo {len(ts_clean)} puntos, se necesitan al menos 30)"
    try:
        model = ARIMA(ts_clean, order=(1,1,1))
        fit = model.fit(method_kwargs={'maxiter': 100}, disp=False)
        forecast = fit.forecast(steps=horizon)
        return forecast.iloc[-1], None
    except Exception as e:
        error_msg = str(e)
        if "convergence" in error_msg.lower() or "singular" in error_msg.lower():
            return None, "ARIMA no pudo converger con estos datos (quizás la serie es muy corta o plana)"
        return None, f"Error ajustando ARIMA: {error_msg[:100]}"

def _monte_carlo_simulation(close: pd.Series, days: int = 1, simulations: int = 1000) -> dict:
    log_returns = np.log(close / close.shift(1)).dropna()
    mu = log_returns.mean()
    sigma = log_returns.std()
    last_price = close.iloc[-1]
    results = []
    for _ in range(simulations):
        returns = np.random.normal(mu, sigma, days)
        price = last_price * np.exp(np.sum(returns))
        results.append(price)
    results = np.array(results)
    prob_up = np.mean(results > last_price)
    percentile_5 = np.percentile(results, 5)
    percentile_95 = np.percentile(results, 95)
    mean_price = np.mean(results)
    return {
        "prob_up": round(float(prob_up), 3),
        "p5": round(float(percentile_5), 2),
        "p95": round(float(percentile_95), 2),
        "mean_price": round(float(mean_price), 2),
        "last_price": last_price
    }

def _kaufman_efficiency_ratio(close: pd.Series, period: int = 10) -> pd.Series:
    change = close.diff(period).abs()
    volatility = close.diff().abs().rolling(window=period).sum()
    er = change / volatility
    return er

def _adaptive_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    return close.pct_change().rolling(window=period).std() * np.sqrt(365)

def perform_advanced_analysis(symbol: str) -> dict:
    INTERVAL = "1d"
    LIMIT = 200
    df = _get_klines(symbol, INTERVAL, LIMIT)
    if df.empty or len(df) < 50:
        return {"error": f"Datos insuficientes para {symbol}"}

    close = df['Close'].copy()
    last_price = close.iloc[-1]

    hurst_val = _hurst(close)
    arima_pred, arima_error = _arima_forecast(close)
    mc = _monte_carlo_simulation(close, days=1, simulations=1000)
    er = _kaufman_efficiency_ratio(close, period=10).iloc[-1]
    fast_ema = close.ewm(span=2, adjust=False).mean()
    slow_ema = close.ewm(span=30, adjust=False).mean()
    ama = (er * fast_ema + (1 - er) * slow_ema).iloc[-1] if not pd.isna(er) else close.iloc[-1]
    vol = _adaptive_volatility(close, 20).iloc[-1]

    atr_series = calculate_atr(df, period=14)
    current_atr = atr_series.iloc[-1] if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else last_price * 0.02

    bullish_signals = 0
    bearish_signals = 0
    if last_price > ama:
        bullish_signals += 1 if hurst_val > 0.5 else 0
    else:
        bearish_signals += 1 if hurst_val > 0.5 else 0
    if arima_pred:
        if arima_pred > last_price:
            bullish_signals += 1
        else:
            bearish_signals += 1
    if mc["prob_up"] > 0.5:
        bullish_signals += 1
    else:
        bearish_signals += 1
    if not pd.isna(er) and er > 0.6:
        if last_price > ama:
            bullish_signals += 1
        else:
            bearish_signals += 1

    direction = "LONG" if bullish_signals >= bearish_signals else "SHORT"
    entry_price = last_price
    if direction == "LONG":
        target_price = round(entry_price * 1.05, 2)
        stop_loss = round(entry_price * 0.98, 2)
    else:
        target_price = round(entry_price * 0.95, 2)
        stop_loss = round(entry_price * 1.02, 2)

    trend = "alcista persistente" if hurst_val > 0.5 else "reversión a la media" if hurst_val < 0.5 else "aleatorio"
    mc_text = f"Prob. suba: {mc['prob_up']*100:.1f}% (rango 5-95%: {mc['p5']} - {mc['p95']})"

    results_text = (
        f"📈 **Análisis Avanzado {symbol}**\n\n"
        f"Precio actual: ${entry_price:.2f}\n"
        f"Exponente de Hurst: {hurst_val:.3f} → mercado {trend}\n"
    )
    if arima_error:
        results_text += f"Predicción ARIMA: {arima_error}\n"
    else:
        results_text += f"Predicción ARIMA 1d: ${arima_pred:.2f}\n"
    results_text += f"Simulación Monte Carlo (1d): {mc_text}\n"
    if not pd.isna(er):
        results_text += f"Eficiencia de Kaufman (ER): {er:.3f} (cercano a 1 = tendencia fuerte)\n"
    results_text += f"Media Adaptativa (AMA): ${ama:.2f}\n"
    if not pd.isna(vol):
        results_text += f"Volatilidad anualizada: {vol*100:.2f}%\n"

    results_text += (
        f"\n🎯 **Recomendación**: **{direction}**\n"
        f"   Entrada: ${entry_price:.2f}\n"
        f"   Take‑Profit (5%): ${target_price:.2f}\n"
        f"   Stop‑Loss (2%): ${stop_loss:.2f}\n"
        f"   (Referencia ATR 14: ${current_atr:.2f})\n"
    )
    # Ahora incluimos el símbolo en el diccionario de retorno
    return {
        "symbol": symbol,                     # ← nuevo
        "results_text": results_text,
        "direction": direction,
        "prob_up": mc["prob_up"],
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
    }


def _get_all_spot_symbols_under(price_limit: float = 5.0, limit: int = 30) -> list[str]:
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error obteniendo tickers para joyas ocultas: {e}")
        return []

    candidates = []
    for t in data:
        sym = t["symbol"]
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base.upper() in STABLECOINS:
            continue
        last_price = float(t["lastPrice"])
        volume = float(t.get("quoteVolume", 0) or 0)
        if last_price < price_limit and volume > 0:
            candidates.append((sym, volume))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in candidates[:limit]]


def find_hidden_gems() -> str:
    symbols = _get_all_spot_symbols_under(5.0, limit=30)
    if not symbols:
        return "No se pudieron obtener monedas de bajo precio en este momento."

    print(f"[HIDDEN GEMS] Analizando {len(symbols)} monedas...")
    long_candidates = []
    for sym in symbols:
        try:
            res = perform_advanced_analysis(sym)
            if "error" in res:
                continue
            if res["direction"] == "LONG":
                long_candidates.append(res)
        except Exception as e:
            print(f"[HIDDEN GEMS] Error con {sym}: {e}")
        time.sleep(0.2)

    if not long_candidates:
        return "Ninguna de las monedas analizadas mostró una señal clara de LONG en este momento."

    long_candidates.sort(key=lambda x: x["prob_up"], reverse=True)
    top3 = long_candidates[:3]

    result = "💎 **Joyas Ocultas para invertir con poco capital**\n\n"
    for i, gem in enumerate(top3, 1):
        # Ahora sí mostramos el símbolo (ej. 1000SATSUSDT) y lo acortamos para mejor lectura
        symbol_display = gem['symbol'].replace("USDT", "")  # quita el USDT final si quieres
        result += (
            f"🔹 **#{i}  {symbol_display}**\n"
            f"   Entrada: ${gem['entry_price']:.4f}\n"
            f"   Prob. subida (MC): {gem['prob_up']*100:.1f}%\n"
            f"   TP (5%): ${gem['target_price']:.4f}\n"
            f"   SL (2%): ${gem['stop_loss']:.4f}\n\n"
        )
    result += "⚠️ Estas recomendaciones se basan en análisis estadístico avanzado. Opera con responsabilidad."
    return result