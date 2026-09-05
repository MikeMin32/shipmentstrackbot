# Deliverybot

Internal Telegram bot for clone shipments. Authorized users work in a single-message interactive workspace that behaves like a persistent operational notepad.

## Architecture

```
Telegram Bot  →  allowlist, interactive workspace, reminder delivery
SQLite        →  shipments, accounts, teams, reminders, status history
```

Authorized users open `/start` or `/menu` and get the shipment workspace immediately.

## Setup

Python 3.11+.

```bash
cd /path/to/deliverybot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Environment variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs |
| `DATABASE_PATH` | SQLite file (default `./data/shipments.db`) |
| `APP_TIMEZONE` | Timezone used for Home “today/tomorrow” and delivered dates (default `UTC`) |

Secrets stay in `.env`. Do not hardcode tokens in source.

## Local development

```bash
source .venv/bin/activate
python bot.py
```

On startup the bot sets Telegram’s ordinary command menu (`MenuButtonDefault`):

* `/menu` — open the shipment workspace
* `/add` — new shipment
* `/search` — search shipments
* `/cancel` — cancel current input

`/start` and `/menu` open the same Home workspace. Unauthorized users receive **Access denied.**

## Home workspace

Home is one editable Telegram message. Active shipments are grouped by operational status:

| Status | Section |
|---|---|
| `enroute` | ✈️ EN ROUTE |
| `out_for_delivery` | 🚚 OUT FOR DELIVERY |
| `preparing` | 📦 PREPARING |
| `make_label` | 🏷️ MAKE LABEL |
| `standby` | ⏸️ STANDBY |

Delivered and archived shipments do not appear on Home. Empty status sections are omitted.

Rows look like `Oner · 🇩🇪 DE — Mon, Sep 7`. Expected dates use the configured timezone:

* today → `Today, Sep 6`
* tomorrow → `Tomorrow, Sep 7`
* otherwise → `Mon, Sep 7`

Numeric buttons under the message match the visible numbered rows. Pagination edits the same workspace message.

## Security

Users not in `ALLOWED_USER_IDS` get `Access denied.` and no management controls.

`ALLOWED_USER_IDS` must contain at least one integer. Spaces around commas are ignored. Invalid tokens abort startup. Empty/whitespace-only lists abort startup.

## Database backup and migration

The existing SQLite file is upgraded in place. IDs, notes, reminders, and status history are preserved.

**Safest first production upgrade:**

1. Stop `shipment-bot` so nothing is writing.
2. Copy the database (`sqlite3 file.db '.backup backup.db'` is better than a live `cp`).
3. Run schema migration once: `python -m database`
4. Start the bot.
5. Confirm `/start` opens Home.

Helper: `./scripts/backup-db.sh` writes a timestamped copy next to the database (or to a path you pass). It prefers `sqlite3 .backup` and otherwise copies `-wal`/`-shm` companions. It never overwrites the live database file.

If you only `cp shipments.db` while the bot is running, you can miss WAL data. Stop the service or use `.backup`.

On connect (bot or `python -m database`) the app:

* takes a process-level file lock (`DATABASE_PATH.migrate.lock`) then a SQLite `BEGIN EXCLUSIVE`
* creates `accounts`, `client_teams`, and `bot_ui_sessions` if missing
* adds `account_id`, `client_team_id`, `box_weight`, `label_creation_date`, `scanned_in_date`, `delivered_date`
* copies legacy `expected_date` into `expected_delivery_date` when needed
* converts parseable EDD datetimes such as `2026-08-13T18:00:00Z` to `2026-08-13`
* moves unparseable free-text EDD (`tomorrow`, `Wednesday`, …) to `expected_date` and sets `expected_delivery_date` to NULL
* does **not** invent account assignments for old rows (`account_id` stays null → UI shows “No account”)
* remaps legacy statuses `pending` / `working_on` to `standby`

Running migration twice is harmless. A failed migration rolls back and the process does not continue.

WAL mode, a 5s busy timeout (30s during migrate), and `foreign_keys=ON` are set on every connection in `Database.connect()`.

A new status value `delivered` is used for completion. Existing archived rows keep their previous status; the old Complete button used to archive, so those records appear under Archive rather than being rewritten as delivered.

Accounts and client teams are not hard-deleted. Creating a duplicate name is rejected (case-insensitive, trimmed). Referenced rows stay readable.

Account **total** = all non-hard-deleted shipments for that account, including delivered and archived. **Active** on the summary excludes delivered and archived.

Marking delivered sets `delivered` + `delivered_date` (today in `APP_TIMEZONE`) and does not archive. Completing twice keeps the original `delivered_date`. Changing status away from Delivered keeps `delivered_date` as historical data unless you clear it through a later deliberate edit (there is no automatic clear).

## Production deployment

Example layout:

```
/opt/shipment-bot/app          # this repository
/opt/shipment-bot/app/.venv
/opt/shipment-bot/app/.env
```

Example unit: `deploy/shipment-bot.service`.

```bash
sudo cp deploy/shipment-bot.service /etc/systemd/system/
# edit User, WorkingDirectory, and EnvironmentFile
sudo systemctl daemon-reload
sudo systemctl enable --now shipment-bot
```

Checklist:

1. Set `BOT_TOKEN`, `ALLOWED_USER_IDS`, `DATABASE_PATH`, and `APP_TIMEZONE` in `.env`
2. Run `python -m database` after pulling schema changes
3. Start `shipment-bot`
4. Confirm `/start` shows Home status sections
5. Confirm an unauthorized Telegram user cannot use the bot

## Existing service migration

Keep the same `DATABASE_PATH`. After pulling this version:

1. Stop the running bot
2. Back up the SQLite file (`./scripts/backup-db.sh` or `sqlite3 "$DATABASE_PATH" ".backup backup.db"`)
3. Install Python deps (`pip install -r requirements.txt`)
4. Add `APP_TIMEZONE` if it is not already set
5. Run `python -m database`
6. Start the bot process

Example units in `deploy/` run as `YOUR_LINUX_USER`, not root. If an older host still runs the bot as root, keep that only if you must; prefer a dedicated user that can read/write `DATABASE_PATH`.

If an older host still has `shipment-api.service` or Mini App Nginx config from a previous version, disable and remove those units. The bot no longer needs FastAPI or a frontend.

## Tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Statuses

Internal values are unchanged except for the `delivered` status:

| Internal | Display | Home emoji |
|---|---|---|
| `enroute` | En Route | ✈️ |
| `out_for_delivery` | Out For Delivery | 🚚 |
| `preparing` | Preparing | 📦 |
| `make_label` | Make Label | 🏷️ |
| `standby` | Standby | ⏸️ |
| `delivered` | Delivered | ✅ |

Archive is independent of status (`archived = 1`). Completing a shipment sets `delivered` and `delivered_date` (today in `APP_TIMEZONE`) and does not archive it.

Operational shipment dates are `YYYY-MM-DD`. Reminders remain datetimes.

## Project layout

```
.
├── bot.py                 # Telegram bot workspace + reminder worker
├── bot_ui/                # Interactive Telegram workspace (keyboards, calendar, pickers)
├── database/              # SQLite schema, migrations, repositories
├── domain/                # status constants, country helpers
├── handlers/              # bot command/callback handlers
├── services/              # reminder worker
├── deploy/                # systemd example
├── tests/
└── README.md
```
