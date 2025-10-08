from __future__ import annotations
import pandas as pd
from dataclasses import dataclass
from typing import Literal
from indicators import rsi, atr
from strategy import StrategyParams, Signal
from config import CFG
from orderblocks import detect_order_blocks, retest_hits


def evaluate_simple(df_1m: pd.DataFrame, params: StrategyParams) -> Signal:
    df = df_1m.copy()
    if len(df) < max(50, params.bands_length + 10):
        return Signal("NONE")

    length = max(10, min(200, params.bands_length))
    ema = df["close"].ewm(span=length, adjust=False).mean()
    atr_series = atr(df, params.atr_period)
    upper = ema + params.bands_multiplier * atr_series
    lower = ema - params.bands_multiplier * atr_series

    r = rsi(df["close"], params.rsi_period)

    i = len(df) - 1
    price = float(df["close"].iloc[i])
    atr_val = float(atr_series.iloc[i])
    ema_slope_up = ema.iloc[i] > ema.iloc[i - 3]
    ema_slope_dn = ema.iloc[i] < ema.iloc[i - 3]
    rsi_val = float(r.iloc[i])

    # Long candidate
    if price <= float(lower.iloc[i]) and rsi_val <= params.hab_rsi_low and ema_slope_up:
        if CFG.ob_enabled:
            look_df = df.tail(CFG.ob_lookback).copy()
            zones = detect_order_blocks(look_df, atr_period=params.atr_period, swing_lb=3, impulse_atr_mult=CFG.ob_impulse_atr, max_age=CFG.ob_lookback)
            i_local = len(look_df) - 1
            ok = any(z.side == "BULL" and retest_hits(look_df, z, i_local, CFG.ob_retest_tol) for z in zones)
            if not ok:
                return Signal("NONE")
        entry = price
        sl = entry - params.sl_atr_mult * atr_val
        tp1 = entry + params.tp1_atr_mult * atr_val
        tp2 = entry + params.tp2_atr_mult * atr_val
        return Signal("LONG", entry=entry, sl=sl, tp1=tp1, tp2=tp2)

    # Short candidate
    if price >= float(upper.iloc[i]) and rsi_val >= params.hab_rsi_high and ema_slope_dn:
        if CFG.ob_enabled:
            look_df = df.tail(CFG.ob_lookback).copy()
            zones = detect_order_blocks(look_df, atr_period=params.atr_period, swing_lb=3, impulse_atr_mult=CFG.ob_impulse_atr, max_age=CFG.ob_lookback)
            i_local = len(look_df) - 1
            ok = any(z.side == "BEAR" and retest_hits(look_df, z, i_local, CFG.ob_retest_tol) for z in zones)
            if not ok:
                return Signal("NONE")
        entry = price
        sl = entry + params.sl_atr_mult * atr_val
        tp1 = entry - params.tp1_atr_mult * atr_val
        tp2 = entry - params.tp2_atr_mult * atr_val
        return Signal("SHORT", entry=entry, sl=sl, tp1=tp1, tp2=tp2)

    return Signal("NONE")
