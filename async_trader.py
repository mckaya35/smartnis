from __future__ import annotations
import asyncio, time
from datetime import datetime, timezone, timedelta
import pandas as pd

from config import CFG
from exchange.binance_client import BinanceClient
from indicators import to_dataframe
from ws_manager import WSManager
from user_stream import UserStream
from strategy import StrategyParams, evaluate
from simple_strategy import evaluate_simple
from indicators import atr as atr_ind
from notifier.telegram import TelegramNotifier
from telegram_commands import TelegramCommandPoller

BAR_CACHE: dict[tuple[str,str], list[list]] = {}
ACTIVE: dict[str, dict] = {}
DAILY_TRADES: int = 0
LAST_REFRESH: datetime | None = None


def upsert_bar_cache(k: dict) -> None:
    s = k["s"].upper()
    tf = k["i"]
    key = (s, tf)
    o = float(k["o"]); h = float(k["h"]); l = float(k["l"]); c = float(k["c"])
    v = float(k["v"]); ot = int(k["t"]); ct = int(k["T"])
    row = [ot, o, h, l, c, v, ct, 0.0, 0, 0.0, 0.0, ""]
    BAR_CACHE.setdefault(key, []).append(row)
    if len(BAR_CACHE[key]) > 1200:
        BAR_CACHE[key] = BAR_CACHE[key][-800:]


def df_for(symbol: str, tf: str) -> pd.DataFrame:
    rows = BAR_CACHE.get((symbol, tf), [])
    return to_dataframe(rows)


def cid(tag: str, symbol: str) -> str:
    return f"{symbol}-{tag}-{int(time.time()*1000)}"


def maybe_move_to_lock_profit(symbol: str, last_price: float, client: BinanceClient, tg: TelegramNotifier) -> None:
    state = ACTIVE.get(symbol)
    if not state or state.get("be_done"):
        return
    side = state["side"]
    entry = float(state["entry"])
    atr_val = float(state["atr"])
    old_sl = float(state["sl_price"])
    be_trg = CFG.be_trigger_atr_mult * atr_val
    lock_atr = CFG.lock_profit_atr_mult * atr_val
    if side == "BUY":
        target_sl = entry + lock_atr
        if last_price >= entry + be_trg and target_sl > old_sl:
            try:
                if state.get("sl_order_id"):
                    client.cancel_order(symbol, order_id=state["sl_order_id"])
            except Exception:
                pass
            new_sl_fmt = client.format_price(symbol, target_sl)
            resp = client.place_stop_market(symbol, "SELL", new_sl_fmt, close_position=True, reduce_only=True, client_id=cid("SLBE", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            state["sl_order_id"] = resp.get("orderId") if isinstance(resp, dict) else None
            state["sl_price"] = float(new_sl_fmt)
            state["be_done"] = True
            tg.send(f"🔒 {symbol} SL kilit kâr (LONG): {new_sl_fmt}")
    else:
        target_sl = entry - lock_atr
        if last_price <= entry - be_trg and target_sl < old_sl:
            try:
                if state.get("sl_order_id"):
                    client.cancel_order(symbol, order_id=state["sl_order_id"])
            except Exception:
                pass
            new_sl_fmt = client.format_price(symbol, target_sl)
            resp = client.place_stop_market(symbol, "BUY", new_sl_fmt, close_position=True, reduce_only=True, client_id=cid("SLBE", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            state["sl_order_id"] = resp.get("orderId") if isinstance(resp, dict) else None
            state["sl_price"] = float(new_sl_fmt)
            state["be_done"] = True
            tg.send(f"🔒 {symbol} SL kilit kâr (SHORT): {new_sl_fmt}")


def apply_tp2_trailing(symbol: str, last_price: float, client: BinanceClient, tg: TelegramNotifier) -> None:
    state = ACTIVE.get(symbol)
    if not state or not state.get("tp1_hit"):
        return
    side = state["side"]
    entry = float(state["entry"])
    atr_val = float(state["atr"])
    trail = CFG.trail_atr_mult * atr_val
    old_sl = float(state["sl_price"])
    if side == "BUY":
        target_sl = max(old_sl, last_price - trail)
        if target_sl > old_sl:
            try:
                if state.get("sl_order_id"):
                    client.cancel_order(symbol, order_id=state["sl_order_id"])
            except Exception:
                pass
            new_sl_fmt = client.format_price(symbol, target_sl)
            resp = client.place_stop_market(symbol, "SELL", new_sl_fmt, close_position=True, reduce_only=True, client_id=cid("SLTR", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            state["sl_order_id"] = resp.get("orderId") if isinstance(resp, dict) else None
            state["sl_price"] = float(new_sl_fmt)
            tg.send(f"🧭 {symbol} SL trail (LONG): {new_sl_fmt}")
    else:
        target_sl = min(old_sl, last_price + trail)
        if target_sl < old_sl:
            try:
                if state.get("sl_order_id"):
                    client.cancel_order(symbol, order_id=state["sl_order_id"])
            except Exception:
                pass
            new_sl_fmt = client.format_price(symbol, target_sl)
            resp = client.place_stop_market(symbol, "BUY", new_sl_fmt, close_position=True, reduce_only=True, client_id=cid("SLTR", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            state["sl_order_id"] = resp.get("orderId") if isinstance(resp, dict) else None
            state["sl_price"] = float(new_sl_fmt)
            tg.send(f"🧭 {symbol} SL trail (SHORT): {new_sl_fmt}")


async def consume_user_events(us: UserStream, client: BinanceClient, tg: TelegramNotifier) -> None:
    global DAILY_TRADES
    last_day = datetime.now(timezone.utc).date()
    while True:
        evt = await us.get_event()
        try:
            today = datetime.now(timezone.utc).date()
            if today != last_day:
                DAILY_TRADES = 0
                last_day = today

            et = evt.get("e")
            if et == "ACCOUNT_UPDATE":
                acc = evt.get("a", {})
                for p in acc.get("P", []) or []:
                    symbol = p.get("s")
                    try:
                        amt = float(p.get("pa", 0) or 0)
                    except Exception:
                        amt = 0.0
                    if symbol and abs(amt) < 1e-9 and symbol in ACTIVE:
                        ACTIVE.pop(symbol, None)
                        tg.send(f"✅ Pozisyon kapandı: {symbol}")
            elif et == "ORDER_TRADE_UPDATE":
                o = evt.get("o", {})
                symbol = o.get("s")
                order_type = o.get("ot")
                status = o.get("X")
                exec_type = o.get("x")
                if status == "FILLED" and symbol:
                    if order_type == "TAKE_PROFIT_MARKET":
                        # TP1 veya TP2 olabilir: miktara bakmak için ek sorgu gerekir
                        st = ACTIVE.get(symbol)
                        if st and not st.get("tp1_hit"):
                            st["tp1_hit"] = True
                            tg.send(f"📥 {symbol} TP1 filled")
                    elif order_type == "STOP_MARKET":
                        tg.send(f"📥 {symbol} SL filled")
        except Exception:
            pass


async def symbol_refresh_loop(client: BinanceClient, wsm: WSManager, tg: TelegramNotifier) -> None:
    global LAST_REFRESH
    LAST_REFRESH = datetime.now(timezone.utc)
    while True:
        await asyncio.sleep(CFG.symbol_refresh_hours * 3600)
        try:
            symbols = client.get_top_usdt_perp_symbols(30, CFG.exclude_symbols, CFG.preferred_price_max, CFG.low_price_priority_max)[:CFG.max_concurrent_symbols]
            # basit re-subscribe: yeni WSManager başlat (kapanış basit bırakıldı)
            wsm.__init__(symbols, [CFG.entry_tf, CFG.mtf_fast, CFG.mtf_slow1, CFG.mtf_slow2])
            await wsm.start()
            tg.send("🔁 WS symbols refreshed: " + ", ".join(symbols))
            LAST_REFRESH = datetime.now(timezone.utc)
        except Exception as e:
            tg.send(f"⚠️ WS symbol refresh error: {e}")


async def command_loop(client: BinanceClient, tg: TelegramNotifier, poller: TelegramCommandPoller, paused_state: dict) -> None:
    while True:
        await asyncio.sleep(2)
        for (cmd, from_id) in poller.get_commands():
            if CFG.admin_user_id and from_id != str(CFG.admin_user_id):
                continue
            # Komut adını normalize et: "/cmd arg" veya "/cmd@bot" -> "/cmd"
            name = cmd.strip().split()[0].lower()
            if "@" in name:
                name = name.split("@", 1)[0]

            if name == "/pause":
                paused_state["paused"] = True
                tg.send("⏸️ Sistem durduruldu (manuel işlem serbest)")
            elif name == "/resume":
                paused_state["paused"] = False
                tg.send("▶️ Sistem devam ediyor")
            elif name == "/status":
                tg.send(f"ℹ️ RUN_MODE={CFG.run_mode}, Mod={'simple' if CFG.simple_mode else 'advanced'}, Lev={CFG.leverage}x, Size={CFG.order_usdt_size} USDT")
            elif name == "/autocoins":
                try:
                    symbols = client.get_top_usdt_perp_symbols(30, CFG.exclude_symbols, CFG.preferred_price_max, CFG.low_price_priority_max)[:CFG.max_concurrent_symbols]
                    tg.send("🔁 Auto symbols: " + ", ".join(symbols))
                except Exception as e:
                    tg.send(f"⚠️ autocoins error: {e}")
            elif name == "/symbols":
                try:
                    risks = client.get_position_risk()
                    pos = [f"{p.get('symbol')}:{p.get('positionAmt')}" for p in risks if abs(float(p.get('positionAmt',0) or 0))>1e-9]
                    tg.send("ℹ️ Positions: " + (", ".join(pos) if pos else "none"))
                except Exception as e:
                    tg.send(f"⚠️ symbols error: {e}")
            elif name == "/risk":
                tg.send(f"ℹ️ Risk USDT: {CFG.risk_usdt_per_trade}, Leverage: {CFG.leverage}x")
            elif name == "/flat":
                try:
                    risks = client.get_position_risk()
                    for p in risks:
                        symbol = p.get("symbol")
                        amt = float(p.get("positionAmt", 0) or 0)
                        if not symbol or abs(amt) < 1e-9:
                            continue
                        side = "SELL" if amt > 0 else "BUY"
                        qty = client.format_qty(symbol, abs(amt))
                        client.place_market_order(symbol, side, qty, reduce_only=True, client_id=cid("FLAT", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
                    tg.send("🧹 Tüm pozisyonlar kapatıldı (flat)")
                except Exception as e:
                    tg.send(f"⚠️ flat error: {e}")
            elif name in ("/selftest", "selftest"):
                try:
                    await tg.send("🧪 SelfTest başladı...")

                    # 1) Test sembolü: aktif listeden ya da düşmezse BTCUSDT
                    try:
                        top = client.get_top_usdt_perp_symbols(limit=1, min_price=0.0, exclude=["BNB","BTC","ETH","SOL"])
                        symbol = top[0] if top else "BTCUSDT"
                        await tg.send(f"🧪 Symbol seçildi: {symbol}")
                    except Exception as e:
                        symbol = "BTCUSDT"
                        await tg.send(f"🧪 Symbol hatası, BTCUSDT kullanılıyor: {e}")

                    # 2) Piyasa fiyatı ve küçük miktar
                    ticker = client._retry(lambda: client.um.mark_price(symbol=symbol))
                    mark = float(ticker.get("markPrice", "0"))
                    qty = client.format_qty(symbol, max(0.001, (CFG.order_size_usdt or 5.0) / max(mark, 1e-8)))
                    await tg.send(f"🧪 Fiyat: {mark}, Miktar: {qty}")

                    # 3) Post-only (GTX) limit buy (fill olmasın); 2 sn sonra iptal
                    limit_price = client.format_price(symbol, mark * (1 - CFG.maker_offset_bps / 10000.0))
                    res = client._retry(lambda: client.um.new_order(
                        symbol=symbol, side="BUY", type="LIMIT",
                        quantity=qty, price=limit_price, timeInForce="GTX",
                        newClientOrderId=cid("selftest", symbol)
                    ))
                    oid = (res or {}).get("orderId") or (res or {}).get("clientOrderId")
                    await tg.send(f"🧪 GTX LIMIT gönderildi: {symbol} {qty} @{limit_price} (oid={oid})")
                    await asyncio.sleep(2)
                    try:
                        if oid:
                            client.cancel_order(symbol, oid)
                            await tg.send("🧪 Emir iptal edildi")
                    except Exception as e:
                        await tg.send(f"🧪 İptal hatası: {e}")

                    await tg.send("✅ SelfTest tamamlandı!")
                except Exception as e:
                    await tg.send(f"⚠️ SelfTest genel hata: {e}")


async def bars_loop(client: BinanceClient, tg: TelegramNotifier, wsm: WSManager, paused_state: dict) -> None:
    global DAILY_TRADES
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
    while True:
        k = await wsm.get_closed_bar()
        upsert_bar_cache(k)
        symbol = k["s"].upper()
        close_price = float(k["c"]) if k.get("c") is not None else None

        if CFG.trailing_enabled and symbol in ACTIVE and close_price is not None:
            maybe_move_to_lock_profit(symbol, close_price, client, tg)
            apply_tp2_trailing(symbol, close_price, client, tg)

        if paused_state.get("paused"):
            continue

        if DAILY_TRADES >= CFG.max_daily_trades:
            continue

        df1 = df_for(symbol, CFG.entry_tf)
        df5 = df_for(symbol, CFG.mtf_fast)
        df15 = df_for(symbol, CFG.mtf_slow1)
        df1h = df_for(symbol, CFG.mtf_slow2)
        if min(len(df1), len(df5), len(df15), len(df1h)) < 50:
            continue

        sig = evaluate_simple(df1, params) if CFG.simple_mode else evaluate(df1, df5, df15, df1h, params)
        # MTF EMA20/50 gate (5m): trendle aynı yönde değilse sinyali atla
        if CFG.mtf_ema_filter and sig.side != "NONE":
            try:
                ema20 = df5["close"].ewm(span=20, adjust=False).mean().iloc[-1]
                ema50 = df5["close"].ewm(span=50, adjust=False).mean().iloc[-1]
                if sig.side == "LONG" and not (ema20 > ema50):
                    sig.side = "NONE"
                if sig.side == "SHORT" and not (ema20 < ema50):
                    sig.side = "NONE"
            except Exception:
                pass
        if sig.side == "NONE" or None in (sig.entry, sig.sl, sig.tp1, sig.tp2):
            continue

        # LIVE yürütme
        price = float(df1["close"].iloc[-1])
        atr_val = float(atr_ind(df1, CFG.atr_period).iloc[-1])
        side = "BUY" if sig.side == "LONG" else "SELL"
        sl_side = "SELL" if side == "BUY" else "BUY"

        # maker attempt
        try:
            best_price = price * (1 - CFG.maker_offset_bps/10000.0) if side == "BUY" else price * (1 + CFG.maker_offset_bps/10000.0)
            maker_px = client.format_price(symbol, best_price)
            qty_guess = CFG.order_usdt_size * CFG.leverage / max(price, 1e-9)
            qty_guess = client.format_qty(symbol, qty_guess)
            client.client.new_order(symbol=symbol, side=side, type="LIMIT", timeInForce="GTX", price=str(maker_px), quantity=qty_guess, newClientOrderId=cid("MAKER", symbol))
            await asyncio.sleep(CFG.maker_wait_seconds)
        except Exception:
            pass

        # boyut
        if CFG.sizing_mode == "atr":
            stop_dist = max(CFG.sl_atr_mult * atr_val, 1e-9)
            raw_qty = (CFG.risk_usdt_per_trade * CFG.leverage) / stop_dist
        else:
            notional = CFG.order_usdt_size * CFG.leverage
            raw_qty = notional / max(price, 1e-9)
        qty = client.format_qty(symbol, raw_qty)
        if qty <= 0.0 or not client.min_notional_ok(symbol, price, qty):
            continue

        client.set_leverage(symbol, CFG.leverage)

        sl_price_fmt = client.format_price(symbol, float(sig.sl))
        tp1_price = client.format_price(symbol, float(sig.tp1))
        tp2_price = client.format_price(symbol, float(sig.tp2))
        tp_qty = client.format_qty(symbol, qty / 2.0)

        try:
            order = client.place_market_order(symbol, side, qty, client_id=cid("MKT", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            sl_resp = client.place_stop_market(symbol, sl_side, sl_price_fmt, close_position=True, reduce_only=True, client_id=cid("SL", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            client.place_take_profit_market(symbol, sl_side, tp1_price, quantity=tp_qty, reduce_only=True, client_id=cid("TP1", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            client.place_take_profit_market(symbol, sl_side, tp2_price, quantity=tp_qty, reduce_only=True, client_id=cid("TP2", symbol), max_retry=CFG.order_retry_max, backoff_ms=CFG.order_retry_backoff_ms)
            ACTIVE[symbol] = {
                "side": side,
                "entry": float(sig.entry),
                "atr": atr_val,
                "sl_order_id": sl_resp.get("orderId") if isinstance(sl_resp, dict) else None,
                "sl_price": float(sl_price_fmt),
                "be_done": False,
                "tp1_hit": False,
            }
            DAILY_TRADES += 1
            try:
                rsi_now = pd.Series(df1["close"]).pct_change().rolling(14).std().iloc[-1] if "rsi" not in df1.columns else df1["rsi"].iloc[-1]
            except Exception:
                rsi_now = 0.0
            tg.send(f"🟢 LIVE {symbol} {side} qty={qty} entry≈{price:.6f} sl={sl_price_fmt} | ATR={atr_val:.6f} RSI≈{float(rsi_now):.2f}")
        except Exception as e:
            tg.send(f"⚠️ LIVE order error {symbol}: {e}")


async def main():
    client = BinanceClient(CFG.binance_api_key, CFG.binance_api_secret)
    tg = TelegramNotifier(CFG.telegram_bot_token, CFG.telegram_chat_id)
    poller = TelegramCommandPoller(CFG.telegram_bot_token, CFG.telegram_chat_id)

    symbols = client.get_top_usdt_perp_symbols(30, CFG.exclude_symbols, CFG.preferred_price_max, CFG.low_price_priority_max)[:CFG.max_concurrent_symbols]

    wsm = WSManager(symbols, [CFG.entry_tf, CFG.mtf_fast, CFG.mtf_slow1, CFG.mtf_slow2])
    us = UserStream(CFG.binance_api_key, CFG.binance_api_secret)

    tg.send("🔌 WS trader started (LIVE/PAPER)")
    await asyncio.gather(wsm.start(), us.start())

    paused_state = {"paused": False}
    await asyncio.gather(
        bars_loop(client, tg, wsm, paused_state),
        consume_user_events(us, client, tg),
        symbol_refresh_loop(client, wsm, tg),
        command_loop(client, tg, poller, paused_state),
    )


if __name__ == "__main__":
    asyncio.run(main())
