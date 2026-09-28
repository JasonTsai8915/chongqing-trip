"""技術指標計算（純函式，不依賴網路）。"""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI（與看盤軟體常用算法一致）。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    # 全漲無跌時 avg_loss 為 0 → RSI = 100
    out[(avg_loss == 0) & avg_gain.notna()] = 100.0
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """回傳 DIF、MACD(訊號線)、OSC(柱狀體 = DIF - MACD)。"""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": dif - dea})


def kd(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9) -> pd.DataFrame:
    """台股常用 KD(9,3,3)。"""
    lowest = low.rolling(period, min_periods=1).min()
    highest = high.rolling(period, min_periods=1).max()
    rng = (highest - lowest).replace(0, pd.NA)
    rsv = ((close - lowest) / rng * 100).fillna(50).astype(float)
    k_vals, d_vals = [], []
    k_prev = d_prev = 50.0
    for v in rsv:
        k_prev = k_prev * 2 / 3 + v / 3
        d_prev = d_prev * 2 / 3 + k_prev / 3
        k_vals.append(k_prev)
        d_vals.append(d_prev)
    return pd.DataFrame({"k": k_vals, "d": d_vals}, index=close.index)


def add_all(df: pd.DataFrame, ma_windows=(5, 10, 20, 60), rsi_period: int = 14) -> pd.DataFrame:
    """在 OHLCV DataFrame 上加上所有指標欄位。"""
    out = df.copy()
    for w in ma_windows:
        out[f"ma{w}"] = sma(out["close"], w)
    out["rsi"] = rsi(out["close"], rsi_period)
    out = out.join(macd(out["close"]))
    out = out.join(kd(out["high"], out["low"], out["close"]))
    out["vol_ma5"] = sma(out["volume"], 5)
    return out
