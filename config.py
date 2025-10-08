import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get_list(var_name: str, default: str) -> list[str]:
    value = os.getenv(var_name, default)
    return [v.strip() for v in value.split(',') if v.strip()]


@dataclass
class Config:
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    leverage: int = int(os.getenv("LEVERAGE", "15"))
    order_usdt_size: float = float(os.getenv("ORDER_USDT_SIZE", "20"))
    max_concurrent_symbols: int = int(os.getenv("MAX_CONCURRENT_SYMBOLS", "8"))

    entry_tf: str = os.getenv("ENTRY_TIMEFRAME", "1m")
    mtf_fast: str = os.getenv("MTF_FAST", "5m")
    mtf_slow1: str = os.getenv("MTF_SLOW_1", "15m")
    mtf_slow2: str = os.getenv("MTF_SLOW_2", "1h")

    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    hab_rsi_low: float = float(os.getenv("HAB_RSI_LOW", "25"))
    hab_rsi_high: float = float(os.getenv("HAB_RSI_HIGH", "80"))

    bands_length: int = int(os.getenv("BANDS_LENGTH", "20"))
    bands_multiplier: float = float(os.getenv("BANDS_MULTIPLIER", "1.0"))
    retest_tolerance_pct: float = float(os.getenv("RETEST_TOLERANCE_PCT", "0.003"))

    atr_period: int = int(os.getenv("ATR_PERIOD", "14"))
    sl_atr_mult: float = float(os.getenv("SL_ATR_MULT", "0.4"))
    tp1_atr_mult: float = float(os.getenv("TP1_ATR_MULT", "0.8"))
    tp2_atr_mult: float = float(os.getenv("TP2_ATR_MULT", "1.2"))
    smart_close_adj_pct: float = float(os.getenv("SMART_CLOSE_ADJ_PCT", "0.001"))

    symbol_refresh_hours: int = int(os.getenv("SYMBOL_REFRESH_HOURS", "6"))
    exclude_symbols: list[str] = tuple(_get_list("EXCLUDE_SYMBOLS", "BNBUSDT,BTCUSDT,ETHUSDT,SOLUSDT"))

    preferred_price_max: float = float(os.getenv("PREFERRED_PRICE_MAX", "100"))
    low_price_priority_max: float = float(os.getenv("LOW_PRICE_PRIORITY_MAX", "1"))

    cooldown_bars: int = int(os.getenv("COOLDOWN_BARS", "3"))
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "15"))

    # Modes and control
    simple_mode: bool = os.getenv("SIMPLE_MODE", "true").lower() == "true"
    paused: bool = os.getenv("PAUSED", "false").lower() == "true"
    run_mode: str = os.getenv("RUN_MODE", "LIVE")  # BACKTEST | PAPER | LIVE

    # Trailing / Breakeven lock profit
    trailing_enabled: bool = os.getenv("TRAILING_ENABLED", "true").lower() == "true"
    be_trigger_atr_mult: float = float(os.getenv("BE_TRIGGER_ATR_MULT", "0.8"))
    lock_profit_atr_mult: float = float(os.getenv("LOCK_PROFIT_ATR_MULT", "0.1"))
    trail_atr_mult: float = float(os.getenv("TRAIL_ATR_MULT", "1.0"))

    # Sizing
    sizing_mode: str = os.getenv("SIZING_MODE", "fixed")  # fixed | atr
    risk_usdt_per_trade: float = float(os.getenv("RISK_USDT_PER_TRADE", "5"))

    # State
    state_path: str = os.getenv("STATE_PATH", "state.json")

    # Admin & risk guards
    admin_user_id: str = os.getenv("ADMIN_USER_ID", "")
    daily_dd_limit_usdt: float = float(os.getenv("DAILY_DD_LIMIT_USDT", "10"))
    max_losing_streak: int = int(os.getenv("MAX_LOSING_STREAK", "3"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
    max_daily_trades: int = int(os.getenv("MAX_DAILY_TRADES", "50"))

    # Drift & retry
    time_drift_max_ms: int = int(os.getenv("TIME_DRIFT_MAX_MS", "1500"))
    order_retry_max: int = int(os.getenv("ORDER_RETRY_MAX", "3"))
    order_retry_backoff_ms: int = int(os.getenv("ORDER_RETRY_BACKOFF_MS", "400"))

    # Order Block filter
    ob_enabled: bool = os.getenv("OB_ENABLED", "false").lower() == "true"
    ob_lookback: int = int(os.getenv("OB_LOOKBACK", "300"))
    ob_impulse_atr: float = float(os.getenv("OB_IMPULSE_ATR", "1.5"))
    ob_retest_tol: float = float(os.getenv("OB_RETEST_TOL", "0.001"))

    # Maker attempt
    maker_offset_bps: float = float(os.getenv("MAKER_OFFSET_BPS", "5"))
    maker_wait_seconds: float = float(os.getenv("MAKER_WAIT_SECONDS", "2"))

    # MTF EMA filter (5m EMA20/50 trend gate)
    mtf_ema_filter: bool = os.getenv("MTF_EMA_FILTER", "false").lower() == "true"


CFG = Config()
