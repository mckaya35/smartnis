from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import pandas as pd

from indicators import heikin_ashi, rsi, atr, faytterro_bands, ssl_channel, supertrend, taker_flow_direction
from config import CFG
from orderblocks import detect_order_blocks, retest_hits


SignalSide = Literal["LONG", "SHORT", "NONE"]


@dataclass
class StrategyParams:
    rsi_period: int
    hab_rsi_low: float
    hab_rsi_high: float
    bands_length: int
    bands_multiplier: float
    retest_tolerance_pct: float
    atr_period: int
    sl_atr_mult: float
    tp1_atr_mult: float
    tp2_atr_mult: float
    smart_close_adj_pct: float


@dataclass
class Signal:
    side: SignalSide
    entry: float | None = None
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None


def _align_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    df = heikin_ashi(df)
    df["rsi"] = rsi(df["close"], params.rsi_period)
    df["atr"] = atr(df, params.atr_period)
    df = faytterro_bands(df, params.bands_length, params.bands_multiplier)
    df = ssl_channel(df, length=10)
    df = supertrend(df, period=10, multiplier=3.0)
    return df


def _retest_ok(df: pd.DataFrame, idx: int, band_col: str, tol_pct: float) -> bool:
    # Check price came back within tolerance to band after a break
    if idx < 2:
        return False
    band = float(df[band_col].iloc[idx])
    price = float(df["close"].iloc[idx])
    return abs(price - band) / max(band, 1e-9) <= tol_pct


def evaluate(
    df_1m: pd.DataFrame,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    params: StrategyParams,
) -> Signal:
    df = _align_indicators(df_1m.copy(), params)
    if len(df) < 50:
        return Signal("NONE")
    i = len(df) - 1

    # Order heat filter using taker buy fraction and price move across last 3 bars
    flow_dir = taker_flow_direction(df, n=3)

    # Heikin Ashi last 3 bodies alignment with trend
    if not (
        df["ha_body_dir"].iloc[i-2:i+1].sum() == 3 or df["ha_body_dir"].iloc[i-2:i+1].sum() == -3
    ):
        return Signal("NONE")

    body_sum = df["ha_body_dir"].iloc[i-2:i+1].sum()

    # Bands context and retest
    touched_lower = df["low"].iloc[i] <= df["fb_lower"].iloc[i]
    touched_upper = df["high"].iloc[i] >= df["fb_upper"].iloc[i]

    retest_lower_ok = _retest_ok(df, i, "fb_lower", params.retest_tolerance_pct)
    retest_upper_ok = _retest_ok(df, i, "fb_upper", params.retest_tolerance_pct)

    # RSI (HAB) gates
    rsi_val = float(df["rsi"].iloc[i])

    # MTF direction via RSI trend on higher TFs
    df5 = df_5m.copy()
    df15 = df_15m.copy()
    df1h = df_1h.copy()
    df5["rsi"] = rsi(df5["close"], params.rsi_period)
    df15["rsi"] = rsi(df15["close"], params.rsi_period)
    df1h["rsi"] = rsi(df1h["close"], params.rsi_period)

    mtf_up = df5["rsi"].iloc[-1] >= df5["rsi"].iloc[-3] and df15["rsi"].iloc[-1] >= df15["rsi"].iloc[-3] and df1h["rsi"].iloc[-1] >= df1h["rsi"].iloc[-3]
    mtf_dn = df5["rsi"].iloc[-1] <= df5["rsi"].iloc[-3] and df15["rsi"].iloc[-1] <= df15["rsi"].iloc[-3] and df1h["rsi"].iloc[-1] <= df1h["rsi"].iloc[-3]

    # Trend confirmation: SSL + Supertrend agree
    df_ssl = ssl_channel(df, length=10)
    df_st = supertrend(df, period=10, multiplier=3.0)
    ssl_dir = int(df_ssl["ssl_dir"].iloc[i])
    st_dir = int(df_st["st_dir"].iloc[i])

    atr_val = float(df["atr"].iloc[i])
    price = float(df["close"].iloc[i])

    # Optional OB retest confirmation
    def ob_confirms(side: str) -> bool:
        if not CFG.ob_enabled:
            return True
        look_df = df.tail(CFG.ob_lookback).copy()
        zones = detect_order_blocks(look_df, atr_period=params.atr_period, swing_lb=3, impulse_atr_mult=CFG.ob_impulse_atr, max_age=CFG.ob_lookback)
        i_local = len(look_df) - 1
        if side == "LONG":
            return any(z.side == "BULL" and retest_hits(look_df, z, i_local, CFG.ob_retest_tol) for z in zones)
        else:
            return any(z.side == "BEAR" and retest_hits(look_df, z, i_local, CFG.ob_retest_tol) for z in zones)

    # Long conditions
    if (
        body_sum == 3 and flow_dir >= 0 and touched_lower and retest_lower_ok and rsi_val <= params.hab_rsi_low and mtf_up and ssl_dir > 0 and st_dir > 0 and ob_confirms("LONG")
    ):
        entry = price
        sl = max(price - params.sl_atr_mult * atr_val, df["low"].iloc[i])
        tp1 = price + params.tp1_atr_mult * atr_val
        tp2 = price + params.tp2_atr_mult * atr_val
        return Signal("LONG", entry=entry, sl=sl, tp1=tp1, tp2=tp2)

    # Short conditions
    if (
        body_sum == -3 and flow_dir <= 0 and touched_upper and retest_upper_ok and rsi_val >= params.hab_rsi_high and mtf_dn and ssl_dir < 0 and st_dir < 0 and ob_confirms("SHORT")
    ):
        entry = price
        sl = min(price + params.sl_atr_mult * atr_val, df["high"].iloc[i])
        tp1 = price - params.tp1_atr_mult * atr_val
        tp2 = price - params.tp2_atr_mult * atr_val
        return Signal("SHORT", entry=entry, sl=sl, tp1=tp1, tp2=tp2)

    return Signal("NONE")
