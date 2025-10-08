# Smart Nis V2.5 Trader Bot

## Prerequisites
- Ubuntu 24.04, Python 3.10+
- Binance USDT-M Futures API key/secret (Futures yetkili)
- Telegram Bot token ve chat id

## Setup
```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
# .env dosyasını düzenleyin
```

## Run
```bash
source .venv/bin/activate
python trader.py
```

## Run (Async WS)
```bash
source .venv/bin/activate
python async_trader.py
```

## Backtest (basit)
```bash
source .venv/bin/activate
python backtest.py
```

## Environment (özet)
- Leverage/size: `LEVERAGE=15`, `ORDER_USDT_SIZE=20` (veya `SIZING_MODE=atr`, `RISK_USDT_PER_TRADE=5`)
- Modlar: `SIMPLE_MODE=true|false`, `PAUSED=false`
- Trailing/Lock: `TRAILING_ENABLED=true`, `BE_TRIGGER_ATR_MULT=0.8`, `LOCK_PROFIT_ATR_MULT=0.1`
- Zaman/MTF: `ENTRY_TIMEFRAME=1m`, `MTF_FAST=5m`, `MTF_SLOW_1=15m`, `MTF_SLOW_2=1h`
- OB (opsiyonel): `OB_ENABLED=false`, `OB_LOOKBACK=300`, `OB_IMPULSE_ATR=1.5`, `OB_RETEST_TOL=0.001`

## Telegram Komutları
- `/mode simple` veya `/mode advanced` — strateji modu
- `/pause` ve `/resume` — botu durdur/başlat (pause iken manuel işlem yapabilirsiniz)
- `/size 20` — sabit USDT pozisyon büyüklüğü
- `/lev 15` — kaldıraç (symbol başına değiştirilir)
- `/status` — durum özeti
 
Günlük özet ve state
- Bot günlük PnL özetini Telegram'a yollar (Binance income verisi ile). 
- `STATE_PATH=state.json` dosyasında aktif durum (SL takip için) saklanır.

## Notlar
- Basit mod: EMA eğimi + Keltner (EMA ± mult·ATR) + RSI kapısı
- Gelişmiş mod: HA + Order Heat + Faytterro benzeri bant + SSL + Supertrend + MTF RSI
- TP/SL: ATR tabanlı; Smart Close ile TP’ye %0.1 kala kapama. Breakeven kilit kâr (entry ± 0.1·ATR) devreye girer.
- Sembol listesi 6 saatte bir yenilenir; blacklist ve fiyat filtreleri uygulanır.

## systemd Servis (Ubuntu)
1) Projeyi sunucuya kopyalayın: `/opt/smartnis`
2) Sanal ortamı kurun ve bağımlılıkları yükleyin
3) Unit dosyasını yerleştirin ve etkinleştirin:
```bash
sudo mkdir -p /var/log
sudo touch /var/log/smartnis.log /var/log/smartnis.err
sudo cp systemd/smartnis.service /etc/systemd/system/smartnis.service
sudo systemctl daemon-reload
sudo systemctl enable --now smartnis
sudo systemctl status smartnis
tail -f /var/log/smartnis.log
```
