# Runbook

## Prereqs
- Ubuntu 24.04, Python 3.12+
- Binance USDT-M API key (Futures)
- Telegram bot token + chat id

## Setup
```bash
sudo apt update && sudo apt install -y python3.12-venv git
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
# edit .env
```

## Run (sync)
```bash
source .venv/bin/activate
python trader.py
```

## Run (async WS)
```bash
source .venv/bin/activate
python async_trader.py
```

## Telegram commands
- /mode simple | /mode advanced
- /pause | /resume | /flat
- /size 20 | /lev 15 | /status

## Logs
- JSON logs at logs/app.log (rotation enabled)

## Common issues
- MinNotional/step/tick: increase size or pick better symbol
- Time drift warning: enable NTP
- 429/5xx: auto-retry with backoff; monitor logs
