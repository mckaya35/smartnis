from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, List
import pandas as pd
import numpy as np
from indicators import atr

Side = Literal["BULL", "BEAR"]

@dataclass
class OrderBlock:
    side: Side
    idx: int           # breakout bar index
    src_idx: int       # last opposite candle index (OB candle)
    low: float
    high: float
    created_at: int    # bar index when created


def _is_swing(series: pd.Series, i: int, lb: int) -> tuple[bool, bool]:
    if i < lb or i >= len(series) - lb:
        return (False, False)
    window = series.iloc[i-lb:i+lb+1]
    val = series.iloc[i]
    is_hi = val >= window.max()
    is_lo = val <= window.min()
    return (is_hi, is_lo)


def detect_order_blocks(
    df: pd.DataFrame,
    atr_period: int = 14,
    swing_lb: int = 3,
    impulse_atr_mult: float = 1.5,
    max_age: int = 200,
) -> List[OrderBlock]:
    a = atr(df, atr_period).fillna(0.0)
    highs, lows, closes, opens = df["high"].values, df["low"].values, df["close"].values, df["open"].values

    last_swing_high = None
    last_swing_low = None
    zones: List[OrderBlock] = []

    for i in range(len(df)):
        hi_flag, _ = _is_swing(df["high"], i, swing_lb)
        _, lo_flag = _is_swing(df["low"], i, swing_lb)
        if hi_flag:
            last_swing_high = (i, highs[i])
        if lo_flag:
            last_swing_low = (i, lows[i])

        if a.iloc[i] <= 0:
            continue

        # Bullish BOS
        if last_swing_high and closes[i] > last_swing_high[1] and (closes[i] - last_swing_high[1]) >= impulse_atr_mult * a.iloc[i]:
            src_idx = None
            for j in range(i-1, max(i-10, 0), -1):
                if closes[j] < opens[j]:  # down candle
                    src_idx = j
                    break
            if src_idx is not None:
                low_z = lows[src_idx]
                high_z = max(opens[src_idx], closes[src_idx])
                zones.append(OrderBlock(side="BULL", idx=i, src_idx=src_idx, low=low_z, high=high_z, created_at=i))

        # Bearish BOS
        if last_swing_low and closes[i] < last_swing_low[1] and (last_swing_low[1] - closes[i]) >= impulse_atr_mult * a.iloc[i]:
            src_idx = None
            for j in range(i-1, max(i-10, 0), -1):
                if closes[j] > opens[j]:  # up candle
                    src_idx = j
                    break
            if src_idx is not None:
                low_z = min(opens[src_idx], closes[src_idx])
                high_z = highs[src_idx]
                zones.append(OrderBlock(side="BEAR", idx=i, src_idx=src_idx, low=low_z, high=high_z, created_at=i))

    last_i = len(df) - 1
    zones = [z for z in zones if (last_i - z.created_at) <= max_age]
    return zones


def retest_hits(df: pd.DataFrame, zone: OrderBlock, i: int, tol_pct: float = 0.001) -> bool:
    hi = float(df["high"].iloc[i])
    lo = float(df["low"].iloc[i])
    low_z = zone.low * (1 - tol_pct)
    high_z = zone.high * (1 + tol_pct)
    return not (hi < low_z or lo > high_z)
