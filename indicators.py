from __future__ import annotations
import numpy as np
import pandas as pd


def to_dataframe(klines: list[list[str | float]]) -> pd.DataFrame:
    cols = [
        "open_time","open","high","low","close","volume","close_time","quote_volume",
        "num_trades","taker_base","taker_quote","ignore"
    ]
    df = pd.DataFrame(klines, columns=cols)
    for c in ["open","high","low","close","volume","taker_base","taker_quote"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    return df


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha = df.copy()
    ha["ha_close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    ha_open = [df["open"].iloc[0]]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i-1] + ha["ha_close"].iloc[i-1]) / 2.0)
    ha["ha_open"] = ha_open
    ha["ha_high"] = ha[["high", "ha_open", "ha_close"]].max(axis=1)
    ha["ha_low"] = ha[["low", "ha_open", "ha_close"]].min(axis=1)
    ha["ha_body_dir"] = np.sign(ha["ha_close"] - ha["ha_open"])  # +1 long body, -1 short body
    return ha


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.rolling(period).mean()


def faytterro_bands(df: pd.DataFrame, length: int = 90, mult: float = 1.0) -> pd.DataFrame:
    # Bollinger-like bands over close as an approximation
    ma = df["close"].rolling(length).mean()
    std = df["close"].rolling(length).std(ddof=0)
    upper = ma + mult * std
    lower = ma - mult * std
    out = df.copy()
    out["fb_mid"] = ma
    out["fb_upper"] = upper
    out["fb_lower"] = lower
    return out


def ssl_channel(df: pd.DataFrame, length: int = 10) -> pd.DataFrame:
    # Classic SSL Channel: MAs of high and low
    sma_high = df["high"].rolling(length).mean()
    sma_low = df["low"].rolling(length).mean()
    hlv = np.where(df["close"] > sma_high, 1, np.where(df["close"] < sma_low, -1, np.nan))
    # forward fill direction when inside channel
    hlv = pd.Series(hlv).fillna(method="ffill").fillna(0)
    ssl_up = np.where(hlv < 0, sma_high, sma_low)
    ssl_dn = np.where(hlv < 0, sma_low, sma_high)
    out = df.copy()
    out["ssl_up"] = ssl_up
    out["ssl_dn"] = ssl_dn
    out["ssl_dir"] = np.sign(out["ssl_up"] - out["ssl_dn"])  # +1 bull, -1 bear
    return out


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    tr = true_range(df)
    atr_ = tr.rolling(period).mean()
    hl2 = (df["high"] + df["low"]) / 2.0
    upperband = hl2 + multiplier * atr_
    lowerband = hl2 - multiplier * atr_

    final_upperband = upperband.copy()
    final_lowerband = lowerband.copy()

    trend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=float)

    for i in range(len(df)):
        if i == 0:
            trend.iloc[i] = np.nan
            direction.iloc[i] = 1
            continue
        final_upperband.iloc[i] = min(upperband.iloc[i], final_upperband.iloc[i-1]) if df["close"].iloc[i-1] > final_upperband.iloc[i-1] else upperband.iloc[i]
        final_lowerband.iloc[i] = max(lowerband.iloc[i], final_lowerband.iloc[i-1]) if df["close"].iloc[i-1] < final_lowerband.iloc[i-1] else lowerband.iloc[i]

        if df["close"].iloc[i] > final_upperband.iloc[i-1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i] < final_lowerband.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]
            if direction.iloc[i] > 0 and final_lowerband.iloc[i] < final_lowerband.iloc[i-1]:
                final_lowerband.iloc[i] = final_lowerband.iloc[i-1]
            if direction.iloc[i] < 0 and final_upperband.iloc[i] > final_upperband.iloc[i-1]:
                final_upperband.iloc[i] = final_upperband.iloc[i-1]

        trend.iloc[i] = final_lowerband.iloc[i] if direction.iloc[i] > 0 else final_upperband.iloc[i]

    out = df.copy()
    out["st_trend"] = trend
    out["st_dir"] = np.sign(direction).fillna(0)
    return out


def last_n_same_sign(series: pd.Series, n: int, sign: int) -> bool:
    part = series.dropna().iloc[-n:]
    if len(part) < n:
        return False
    return (np.sign(part) == sign).all()


def taker_flow_direction(df: pd.DataFrame, n: int = 3) -> int:
    # Approximate order heat: compare taker buy volume vs total and price change
    dirs: list[int] = []
    for i in range(len(df)-n, len(df)):
        if i < 1:
            continue
        tb = float(df["taker_base"].iloc[i])
        vol = float(df["volume"].iloc[i]) + 1e-12
        frac = tb / vol
        price_dir = np.sign(df["close"].iloc[i] - df["close"].iloc[i-1])
        dirs.append(1 if (frac > 0.5 and price_dir >= 0) else (-1 if (frac < 0.5 and price_dir <= 0) else 0))
    s = sum(dirs)
    return 1 if s >= n-1 else (-1 if s <= -(n-1) else 0)
