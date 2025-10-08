from __future__ import annotations
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from config import CFG
from exchange.binance_client import BinanceClient
from indicators import to_dataframe
from notifier.telegram import TelegramNotifier
from strategy import StrategyParams, evaluate
from simple_strategy import evaluate_simple
from telegram_commands import TelegramCommandPoller
from indicators import atr as atr_ind
from state_store import load_state, save_state


def fmt_pct(x: float) -> str:
    return f"{x*100:.2f}%"


def adjust_tp_for_smart_close(price: float, side: str, adj_pct: float) -> float:
    if side == "BUY":
        return price * (1.0 - adj_pct)
    else:
        return price * (1.0 + adj_pct)


def usdt_to_qty(symbol: str, price: float, usdt: float, leverage: int, client: BinanceClient) -> float:
    notional = usdt * leverage
    raw_qty = max(notional / max(price, 1e-9), 0.0)
    return client.format_qty(symbol, raw_qty)


def atr_risk_qty(symbol: str, price: float, atr_val: float, risk_usdt: float, sl_atr_mult: float, leverage: int, client: BinanceClient) -> float:
    stop_dist = max(sl_atr_mult * atr_val, 1e-9)
    raw_qty = (risk_usdt * leverage) / stop_dist
    raw_qty = min(raw_qty, (risk_usdt * leverage) / max(price * 0.05, 1e-9))
    qty = client.format_qty(symbol, raw_qty)
    return qty


def load_klines(client: BinanceClient, symbol: str, tf: str, limit: int = 500) -> pd.DataFrame:
    kl = client.get_klines(symbol, tf, limit)
    return to_dataframe(kl)


def format_signal_msg(symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float, rsi_val: float, atr_val: float) -> str:
    arrow = "🔵 LONG" if side == "BUY" else "🔴 SHORT"
    return (
        f"{arrow} {symbol}\n"
        f"Entry: <b>{entry:.6f}</b>\n"
        f"SL: <b>{sl:.6f}</b> | TP1: <b>{tp1:.6f}</b> | TP2: <b>{tp2:.6f}</b>\n"
        f"ATR: <b>{atr_val:.6f}</b>\n"
    )


def maybe_move_to_lock_profit(symbol: str, price: float, client: BinanceClient, state: dict, tg: TelegramNotifier) -> None:
    if state.get("be_done"):
        return
    side = state["side"]
    entry = float(state["entry"])
    atr_val = float(state["atr"])
    old_sl = float(state["sl_price"])
    be_trg = CFG.be_trigger_atr_mult * atr_val
    lock_atr = CFG.lock_profit_atr_mult * atr_val

    if side == "BUY":
        target_sl = entry + lock_atr
        if price >= entry + be_trg and target_sl > old_sl:
            try:
                if state.get("sl_order_id"):
                    client.cancel_order(symbol, order_id=state["sl_order_id"])
            except Exception:
                pass
            new_sl_fmt = client.format_price(symbol, target_sl)
            resp = client.place_stop_market(symbol, "SELL", new_sl_fmt, close_position=True, reduce_only=True)
            state["sl_order_id"] = resp.get("orderId") if isinstance(resp, dict) else None
            state["sl_price"] = float(new_sl_fmt)
            state["be_done"] = True
            tg.send(f"🔒 {symbol} SL kilit kâr (LONG): {new_sl_fmt}")
    else:
        target_sl = entry - lock_atr
        if price <= entry - be_trg and target_sl < old_sl:
            try:
                if state.get("sl_order_id"):
                    client.cancel_order(symbol, order_id=state["sl_order_id"])
            except Exception:
                pass
            new_sl_fmt = client.format_price(symbol, target_sl)
            resp = client.place_stop_market(symbol, "BUY", new_sl_fmt, close_position=True, reduce_only=True)
            state["sl_order_id"] = resp.get("orderId") if isinstance(resp, dict) else None
            state["sl_price"] = float(new_sl_fmt)
            state["be_done"] = True
            tg.send(f"🔒 {symbol} SL kilit kâr (SHORT): {new_sl_fmt}")


def main() -> None:
    client = BinanceClient(CFG.binance_api_key, CFG.binance_api_secret)
    tg = TelegramNotifier(CFG.telegram_bot_token, CFG.telegram_chat_id)
    poller = TelegramCommandPoller(CFG.telegram_bot_token, CFG.telegram_chat_id)

    # server time drift check
    try:
        drift = abs(client.server_time() - int(datetime.now(timezone.utc).timestamp() * 1000))
        if drift > CFG.time_drift_max_ms:
            tg.send(f"⚠️ Saat farkı yüksek: {drift} ms (NTP senkron önerilir)")
    except Exception:
        pass

    last_refresh = datetime.now(timezone.utc) - timedelta(hours=CFG.symbol_refresh_hours)
    symbols: list[str] = []

    cooldown: Dict[Tuple[str, str], datetime] = {}
    active: Dict[str, Dict] = {}

    # Load state
    state = load_state(CFG.state_path)
    if isinstance(state.get("active"), dict):
        active = state["active"]  # type: ignore

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

    mode = "simple" if CFG.simple_mode else "advanced"
    paused = CFG.paused

    tg.send(f"🤖 Başladı. Mod={mode}, Paused={'Evet' if paused else 'Hayır'}, RUN_MODE={CFG.run_mode}")
    last_pnl_sent_day = datetime.now(timezone.utc).date()

    def get_daily_pnl() -> float:
        try:
            start_ms = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            inc = client.income_history(start_time_ms=start_ms)
            return sum(float(i.get("income", 0) or 0) for i in inc)
        except Exception:
            return 0.0

    def update_losing_streak(_state: dict) -> None:
        try:
            inc = client.income_history()
            last = [float(i.get("income", 0) or 0) for i in inc if i.get("incomeType") == "REALIZED_PNL"][-5:]
            streak = 0
            for v in reversed(last):
                if v < 0:
                    streak += 1
                else:
                    break
            _state["losing_streak"] = streak
        except Exception:
            pass

    def cid(tag: str, symbol: str) -> str:
        return f"{symbol}-{tag}-{int(time.time()*1000)}"

    while True:
        now = datetime.now(timezone.utc)

        # Daily PnL summary
        if now.date() != last_pnl_sent_day:
            try:
                pnl = get_daily_pnl()
                tg.send(f"📊 Günlük PnL: {pnl:.2f} USDT")
            except Exception:
                pass
            last_pnl_sent_day = now.date()

        # Handle Telegram commands (admin-only if set)
        for (cmd, from_id) in poller.get_commands():
            if CFG.admin_user_id and from_id != str(CFG.admin_user_id):
                continue
            if cmd.startswith("/mode "):
                if "simple" in cmd:
                    mode = "simple"; tg.send("✅ Mod: Basit")
                elif "advanced" in cmd:
                    mode = "advanced"; tg.send("✅ Mod: Gelişmiş")
            elif cmd == "/pause":
                paused = True; tg.send("⏸️ Sistem durduruldu (manuel işlem serbest)")
            elif cmd == "/resume":
                paused = False; tg.send("▶️ Sistem devam ediyor")
            elif cmd.startswith("/size "):
                try:
                    size = float(cmd.split()[1])
                    os.environ["ORDER_USDT_SIZE"] = str(size)
                    CFG.order_usdt_size = size
                    tg.send(f"✅ Order size: {size} USDT")
                except Exception:
                    tg.send("⚠️ /size kullanım: /size 20")
            elif cmd.startswith("/lev "):
                try:
                    lev = int(cmd.split()[1])
                    os.environ["LEVERAGE"] = str(lev)
                    CFG.leverage = lev
                    tg.send(f"✅ Leverage: {lev}x")
                except Exception:
                    tg.send("⚠️ /lev kullanım: /lev 15")
            elif cmd == "/status":
                tg.send(f"ℹ️ Mod={mode}, Paused={'Evet' if paused else 'Hayır'}, Lev={CFG.leverage}x, Size={CFG.order_usdt_size} USDT, RUN_MODE={CFG.run_mode}")

        # Persist state
        try:
            save_state({"active": active}, CFG.state_path)
        except Exception:
            pass

        # Risk guards
        daily_pnl = get_daily_pnl()
        if daily_pnl <= -abs(CFG.daily_dd_limit_usdt):
            if not paused:
                paused = True
                tg.send(f"⛔ Günlük zarar limiti aşıldı ({daily_pnl:.2f} USDT). Sistem pause.")

        update_losing_streak(state)
        if state.get("losing_streak", 0) >= CFG.max_losing_streak:
            if not paused:
                paused = True
                tg.send(f"⛔ Losing streak {state['losing_streak']}! Sistem pause.")

        # Refresh symbols every N hours
        if not symbols or (now - last_refresh) >= timedelta(hours=CFG.symbol_refresh_hours):
            try:
                symbols = client.get_top_usdt_perp_symbols(
                    top_n=30,
                    exclude=CFG.exclude_symbols,
                    price_max=CFG.preferred_price_max,
                    prefer_low_price_max=CFG.low_price_priority_max,
                )[:CFG.max_concurrent_symbols]
                last_refresh = now
                tg.send("🔁 Symbol list refreshed: " + ", ".join(symbols))
            except Exception as e:
                tg.send(f"⚠️ Symbol refresh error: {e}")

        for symbol in symbols:
            try:
                price = client.get_price(symbol)

                # position cleanup
                try:
                    pos_list = client.get_position_risk(symbol=symbol)
                    pos_amt = 0.0
                    for p in pos_list or []:
                        if p.get("symbol") == symbol:
                            pos_amt = float(p.get("positionAmt", 0.0) or 0.0)
                            break
                    if abs(pos_amt) < 1e-9 and symbol in active:
                        active.pop(symbol, None)
                except Exception:
                    pass

                if CFG.trailing_enabled and symbol in active:
                    maybe_move_to_lock_profit(symbol, price, client, active[symbol], tg)

                if paused:
                    continue

                # max open positions guard
                open_positions_cnt = 0
                try:
                    risks = client.get_position_risk()
                    open_positions_cnt = sum(1 for p in risks if abs(float(p.get("positionAmt", 0) or 0)) > 1e-9)
                except Exception:
                    pass
                if open_positions_cnt >= CFG.max_open_positions:
                    continue

                df1 = load_klines(client, symbol, CFG.entry_tf, limit=500)
                df5 = load_klines(client, symbol, CFG.mtf_fast, limit=300)
                df15 = load_klines(client, symbol, CFG.mtf_slow1, limit=200)
                df1h = load_klines(client, symbol, CFG.mtf_slow2, limit=200)

                sig = evaluate_simple(df1, params) if mode == "simple" else evaluate(df1, df5, df15, df1h, params)
                if sig.side == "NONE" or sig.entry is None or sig.sl is None or sig.tp1 is None or sig.tp2 is None:
                    continue

                side = "BUY" if sig.side == "LONG" else "SELL"
                cd_key = (symbol, side)
                last_time = cooldown.get(cd_key)
                if last_time and (now - last_time) < timedelta(minutes=CFG.cooldown_bars):
                    continue

                client.set_leverage(symbol, CFG.leverage)

                atr_series = atr_ind(df1, CFG.atr_period)
                atr_val = float(atr_series.iloc[-1])

                if CFG.sizing_mode == "atr":
                    qty = atr_risk_qty(symbol, price, atr_val, CFG.risk_usdt_per_trade, CFG.sl_atr_mult, CFG.leverage, client)
                else:
                    qty = usdt_to_qty(symbol, price, CFG.order_usdt_size, CFG.leverage, client)

                if qty <= 0.0 or not client.min_notional_ok(symbol, price, qty):
                    continue

                sl_price = sig.sl
                sl_side = "SELL" if side == "BUY" else "BUY"
                sl_price_fmt = client.format_price(symbol, sl_price)

                tp1_price = client.format_price(symbol, adjust_tp_for_smart_close(sig.tp1, side, params.smart_close_adj_pct))
                tp2_price = client.format_price(symbol, adjust_tp_for_smart_close(sig.tp2, side, params.smart_close_adj_pct))
                tp_qty = client.format_qty(symbol, qty / 2.0)

                if CFG.run_mode.upper() == "PAPER":
                    cooldown[cd_key] = now
                    active[symbol] = {
                        "side": side,
                        "entry": float(sig.entry),
                        "atr": atr_val,
                        "sl_order_id": None,
                        "sl_price": float(sl_price),
                        "be_done": False,
                    }
                    tg.send(f"🧪 PAPER {symbol} {side} entry={sig.entry:.6f} sl={sig.sl:.6f}")
                    time.sleep(0.2)
                    continue

                # LIVE: idempotent + retry
                order = client.place_market_order(symbol, side, qty, client_id=cid("MKT", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
                sl_resp = client.place_stop_market(symbol, sl_side, sl_price_fmt, close_position=True, reduce_only=True, client_id=cid("SL", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
                client.place_take_profit_market(symbol, sl_side, tp1_price, quantity=tp_qty, reduce_only=True, client_id=cid("TP1", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
                client.place_take_profit_market(symbol, sl_side, tp2_price, quantity=tp_qty, reduce_only=True, client_id=cid("TP2", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)

                cooldown[cd_key] = now

                active[symbol] = {
                    "side": side,
                    "entry": float(sig.entry),
                    "atr": atr_val,
                    "sl_order_id": sl_resp.get("orderId") if isinstance(sl_resp, dict) else None,
                    "sl_price": float(sl_price_fmt),
                    "be_done": False,
                }

                tg.send(format_signal_msg(symbol, side, sig.entry, sig.sl, sig.tp1, sig.tp2, 0.0, atr_val))

                time.sleep(1)

            except Exception as e:
                tg.send(f"⚠️ {symbol} error: {e}")
                time.sleep(1)

        time.sleep(CFG.poll_seconds)


if __name__ == "__main__":
    main()
