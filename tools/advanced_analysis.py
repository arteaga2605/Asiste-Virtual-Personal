# tools/advanced_analysis.py
import numpy as np
import pandas as pd
from tools.trading import _get_klines, calculate_atr

def _hurst(ts: pd.Series) -> float:
    """Calcula el exponente de Hurst usando R/S analysis."""
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

def _arima_forecast(ts: pd.Series, horizon: int = 1) -> float | None:
    """ARIMA(1,1,1) simple usando statsmodels. Si falla, devuelve None."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
        model = ARIMA(ts.dropna(), order=(1,1,1))
        fit = model.fit(method_kwargs={'maxiter': 100}, disp=False)
        forecast = fit.forecast(steps=horizon)
        return forecast.iloc[-1]
    except ImportError:
        print("ARIMA no disponible: statsmodels no está instalado.")
        return None
    except Exception as e:
        print(f"ARIMA falló: {e}")
        return None

def _monte_carlo_simulation(close: pd.Series, days: int = 1, simulations: int = 1000) -> dict:
    """Simulación Monte Carlo con GBM. Retorna prob. de subida y percentiles."""
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
    """Ratio de eficiencia de Kaufman."""
    change = close.diff(period).abs()
    volatility = close.diff().abs().rolling(window=period).sum()
    er = change / volatility
    return er

def _adaptive_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """Volatilidad adaptativa (desviación estándar rodante anualizada)."""
    return close.pct_change().rolling(window=period).std() * np.sqrt(365)

def perform_advanced_analysis(symbol: str) -> dict:
    """Realiza análisis avanzado para un símbolo y retorna resultados y prompt."""
    INTERVAL = "1d"
    LIMIT = 200
    df = _get_klines(symbol, INTERVAL, LIMIT)
    if df.empty or len(df) < 50:
        return {"error": f"Datos insuficientes para {symbol}"}

    close = df['Close'].copy()
    last_price = close.iloc[-1]

    # 1. Exponente de Hurst
    hurst_val = _hurst(close)

    # 2. ARIMA
    arima_pred = _arima_forecast(close)
    arima_available = arima_pred is not None

    # 3. Monte Carlo
    mc = _monte_carlo_simulation(close, days=1, simulations=1000)

    # 4. Kaufman Efficiency Ratio
    er = _kaufman_efficiency_ratio(close, period=10).iloc[-1]
    fast_ema = close.ewm(span=2, adjust=False).mean()
    slow_ema = close.ewm(span=30, adjust=False).mean()
    ama = (er * fast_ema + (1 - er) * slow_ema).iloc[-1] if not pd.isna(er) else close.iloc[-1]

    # 5. Volatilidad adaptativa
    vol = _adaptive_volatility(close, 20).iloc[-1]

    # Calcular ATR (14) para referencia
    atr_series = calculate_atr(df, period=14)
    current_atr = atr_series.iloc[-1] if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else last_price * 0.02

    # Determinar dirección combinando señales (sin cambios)
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

    # --- NUEVO: TP y SL basados en porcentajes fijos ---
    entry_price = last_price
    if direction == "LONG":
        target_price = round(entry_price * 1.05, 2)   # +5%
        stop_loss = round(entry_price * 0.98, 2)      # -2%
    else:
        target_price = round(entry_price * 0.95, 2)   # -5%
        stop_loss = round(entry_price * 1.02, 2)      # +2%

    # Construir resultados para mostrar
    trend = "alcista persistente" if hurst_val > 0.5 else "reversión a la media" if hurst_val < 0.5 else "aleatorio"
    mc_text = f"Prob. suba: {mc['prob_up']*100:.1f}% (rango 5-95%: {mc['p5']} - {mc['p95']})"

    results_text = (
        f"📈 **Análisis Avanzado {symbol}**\n\n"
        f"Precio actual: ${entry_price:.2f}\n"
        f"Exponente de Hurst: {hurst_val:.3f} → mercado {trend}\n"
    )
    if arima_available:
        results_text += f"Predicción ARIMA 1d: ${arima_pred:.2f}\n"
    else:
        results_text += "Predicción ARIMA no disponible (instala statsmodels o revisa los datos).\n"
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

    prompt_for_llm = results_text + (
        "\nInterpreta estos resultados y justifica la recomendación en 2 líneas."
    )
    return {"results_text": results_text, "prompt_for_llm": prompt_for_llm}