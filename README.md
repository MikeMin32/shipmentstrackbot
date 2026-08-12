# Shipment Bot

A small Telegram bot for manually managing shipments. Replaces a hand-maintained shipment list in a group chat.

**Stack:** Python 3.11+, aiogram 3.x, SQLite (aiosqlite), long polling.

## Features

- Active summary grouped as EnRoute + Working On / Standby
- Fields: Country, Clone Name, Status, EDD (+ note)
- Add / search / filter by status
- Edit every main field from shipment details
- Manual per-shipment reminders (SQLite-backed, survive restarts)
- Archive / complete (soft archive, no hard deletes)
- Status history table for later analytics
- Allowlist access control via `ALLOWED_USER_IDS`

## Setup (Ubuntu / Linux)

```bash
cd /path/to/deliverybot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot |
| `DATABASE_PATH` | SQLite file path (default `./data/shipments.db`) |

Find your Telegram user ID with [@userinfobot](https://t.me/userinfobot) or similar.

## Run

```bash
source .venv/bin/activate
python bot.py
```

Open the bot in Telegram and send `/start`.

## Statuses

| Internal | Display |
|---|---|
| `standby` | Standby (no emoji in the summary list) |
| `preparing` | 📦 Preparing |
| `make_label` | 📝 Make Label |
| `enroute` | ✈️ EnRoute |
| `out_for_delivery` | 🚚 Out For Delivery |

Main Active Shipments screen uses two display groups only: **EnRoute** and **Working On / Standby**.

EDD and reminders use UTC only, format `YYYY-MM-DD HH:MM` (stored as ISO 8601 UTC). Reminders are polled every ~30 seconds from SQLite.

## systemd (optional)

Create `/etc/systemd/system/shipment-bot.service`:

```ini
[Unit]
Description=Telegram Shipment Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_LINUX_USER
WorkingDirectory=/path/to/deliverybot
Environment=PYTHONUNBUFFERED=1
ExecStart=/path/to/deliverybot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shipment-bot
sudo systemctl status shipment-bot
```

Logs:

```bash
journalctl -u shipment-bot -f
```

## Project layout

```
.
├── bot.py
├── config.py
├── database/
├── handlers/
├── keyboards/
├── middlewares/
├── states/
├── utils/
├── data/
├── .env.example
├── requirements.txt
└── README.md
```

## Notes

- Only users listed in `ALLOWED_USER_IDS` can interact; others get `Access denied.`
- Rows are never hard-deleted from the normal UI (`archived = 1`).
- Expected dates are free text (e.g. `Wednesday`, `Aug 15`), not parsed calendars.
- No carrier APIs or automatic tracking in this MVP.
