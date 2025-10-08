# Codebase Review Report

## Top Findings (High Signal)
1. Idempotent orders with retry/backoff implemented in Binance client; safer under 429/5xx.
2. Step/tick/minNotional rounding handled; reduces order reject risk.
3. RUN_MODE (PAPER/LIVE) gates execution; admin-gated Telegram commands.
4. Circuit breakers: daily DD, losing streak, max open positions, max daily trades.
5. WS async pipeline for kline close; user-data stream for fills/position cleanup.
6. Lock-profit (breakeven+) and optional ATR trailing after TP1.
7. OB retest optional filter; disabled by default.
8. JSON logging with rotation added at `infra/logger.py`.
9. Systemd unit and backtester included; README updated.
10. Security: API keys via env; admin user id check on commands.

## File-Level Notes
- `exchange/binance_client.py`: server_time, retry helper, clientOrderId; rounding via filters.
- `trader.py`: robust controls, state store, daily pnl; Telegram commands.
- `async_trader.py`: WS orchestration, maker attempt + fallback, /flat, trailing.
- `indicators.py` / `strategy.py`: strategy logic intact; optional OB confirmation only.

## Red Flags / Risks
- Maker attempt uses direct `new_order` LIMIT GTX via low-level client; consider wrapper method.
- WS symbol refresh recreates client; assume library closes previous streams (acceptable MVP tradeoff).
- No Prometheus metrics; optional for later.

## Compatibility
- Python 3.12: pinned deps in requirements.txt OK; dev tools in requirements-dev.txt.

## Test Suggestions
- Paper 15 min, TOPN=5; verify TP/SL fills, /flat, maker fallback, daily trade limit.
- Live micro-size single symbol for sanity.
