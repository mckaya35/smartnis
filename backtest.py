from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
from typing import List
import pandas as pd

from exchange.binance_client import BinanceClient
from indicators import to_dataframe
from strategy import StrategyParams, evaluate
from simple_strategy import evaluate_simple
from config import CFG


def run_backtest(symbol: str, start: datetime, end: datetime, mode: str = "simple") -> None:
    client = BinanceClient(CFG.binance_api_key, CFG.binance_api_secret)
    start_ms = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(end.replace(tzinfo=timezone.utc).timestamp() * 1000)

    kl = client.get_klines_range(symbol, CFG.entry_tf, start_ms, end_ms, limit=1500)
    df = to_dataframe(kl)

    params = StrategyParams(
        rsi_period=CFG.rsi_period,
        hab_rsi_low=CFG.hab_rsi_low,
        hab_rsi_high=CFG.hab_rsi_high,
        bands_length=CFG.bands_length,
        bands_multiplier=CFG.bands_multiplier,
        retest_tolerance_pct=CFG.retest_tolerance_pct,
        atr_period=CFG.atr_period,
        sl_atr_mult=CFG.sl_atr_mult,
        tp1_atr_mult=CFG.tp1_atr_mult,
        tp2_atr_mult=CFG.tp2_atr_mult,
        smart_close_adj_pct=CFG.smart_close_adj_pct,
    )

    wins = 0
    losses = 0
    total_r = 0.0

    for i in range(max(200, params.bands_length + 10), len(df)):
        df_slice = df.iloc[: i + 1]
        if mode == "simple":
            sig = evaluate_simple(df_slice, params)
        else:
            # naive MTF same TF for offline demo
            sig = evaluate(df_slice, df_slice, df_slice, df_slice, params)
        if sig.side == "NONE" or sig.entry is None or sig.sl is None or sig.tp1 is None:
            continue
        entry = sig.entry
        sl = sig.sl
        tp = sig.tp1
        # simulate next 20 bars outcome
        outcome = None
        for j in range(i + 1, min(len(df), i + 20)):
            high = df["high"].iloc[j]
            low = df["low"].iloc[j]
            if sig.side == "LONG":
                if low <= sl:
                    outcome = -1
                    break
                if high >= tp:
                    outcome = 1
                    break
            else:
                if high >= sl:
                    outcome = -1
                    break
                if low <= tp:
                    outcome = 1
                    break
        if outcome == 1:
            wins += 1
            total_r += 1.0
        elif outcome == -1:
            losses += 1
            total_r -= 1.0

    trades = wins + losses
    winrate = (wins / trades * 100.0) if trades > 0 else 0.0
    print(f"{symbol} {mode}: trades={trades}, winrate={winrate:.1f}%, totalR={total_r:.1f}")


if __name__ == "__main__":
    s = datetime.now(timezone.utc) - timedelta(days=7)
    e = datetime.now(timezone.utc)
    run_backtest("DOGEUSDT", s, e, mode="simple")
