# Shipment Tracker

Internal operations tool for clone shipments. The **Telegram bot** is the primary day-to-day interface: a single-message interactive workspace that behaves like a persistent notepad. A Telegram Mini App remains available as an optional secondary UI.

## Architecture

```
Telegram Bot  →  allowlist, interactive workspace, reminder delivery
Telegram Mini App (optional)  →  dashboard, CRUD, filters, accounts, archive
    FastAPI backend  →  initData auth, business logic, SQLite
SQLite  →  shared database
```

Authorized users open `/start` or `/menu` and get the shipment workspace immediately. `MINI_APP_URL` is **not required** for the bot to work. If it is set, `/app` (and a More screen action) can still open the Mini App.

## Setup

Python 3.11+.

```bash
cd /path/to/deliverybot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Frontend:

```bash
cd frontend
npm install
```

## Environment variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs |
| `DATABASE_PATH` | SQLite file (default `./data/shipments.db`) |
| `MINI_APP_URL` | Optional HTTPS origin of the Mini App. The bot workspace works without it. |
| `APP_TIMEZONE` | Timezone used for “today” when marking delivered (default `UTC`) |
| `ENVIRONMENT` | `production`, `development`, or `test` (default `production`) |
| `API_HOST` / `API_PORT` | FastAPI bind address (default `127.0.0.1:8000`) |
| `FRONTEND_DIST` | Built Mini App directory if FastAPI serves static files |
| `CORS_ORIGINS` | Browser origins allowed to call the API. Empty in production (same-origin). Local Vite: `http://localhost:5173` |
| `INIT_DATA_MAX_AGE_SECONDS` | Max age of Telegram `initData` (default 86400) |
| `DEV_AUTH_ENABLED` | Dev-only auth bypass; ignored in production |
| `DEV_TELEGRAM_USER_ID` | Allowlisted user id used when dev auth is on |
| `ENABLE_LEGACY_BOT_UI` | Unused. The interactive workspace is always the primary Telegram UI. |

Secrets stay in `.env`. Do not hardcode tokens or Mini App URLs in source.

## Local development

Terminal 1 — API:

```bash
source .venv/bin/activate
export ENVIRONMENT=development
export DEV_AUTH_ENABLED=true
export DEV_TELEGRAM_USER_ID=<an id from ALLOWED_USER_IDS>
python run_api.py
```

Terminal 2 — Mini App:

```bash
cd frontend
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. With dev auth enabled you can open `http://127.0.0.1:5173` in a normal browser. This bypass is disabled whenever `ENVIRONMENT=production`.

Terminal 3 — bot (needs a real `BOT_TOKEN`; Mini App URL is optional):

```bash
source .venv/bin/activate
python bot.py
```

`MINI_APP_URL` is only needed if you want `/app` to open the Mini App. Telegram Mini Apps do not accept `http://localhost` in production. For device testing, put the Mini App behind HTTPS (tunnel or reverse proxy) and set `MINI_APP_URL` to that origin.

## Frontend build

```bash
cd frontend
npm install
npm run typecheck
npm run build
```

Output is `frontend/dist`. Nginx can serve it, or FastAPI will serve it if `FRONTEND_DIST` points at that directory.

## Telegram configuration

Telegram Mini Apps require HTTPS. Set `MINI_APP_URL` to the public frontend origin, with no trailing slash:

```
MINI_APP_URL=https://YOUR_DOMAIN
```

That value is the **frontend** origin (`https://YOUR_DOMAIN`), not the API prefix (`https://YOUR_DOMAIN/api`). `/app` opens `MINI_APP_URL` when configured. Reminder “Open Shipment” buttons open the shipment **inside the bot workspace**, not the Mini App.

### Bot menu button (configured by this app)

This is the Menu Button inside a private chat with the bot.

On startup the bot **resets the default/global menu button** to Telegram’s ordinary command menu (`MenuButtonDefault`). It does **not** attach a Mini App as the primary private-chat menu.

Authorized users who send `/start` or `/menu` receive the interactive shipment workspace. Unauthorized users receive **Access denied.**

If a chat previously received a per-chat Web App menu button, `/start` resets that chat back to the default command menu.

### Main Mini App / Launch App (manual BotFather step)

The code does **not** configure BotFather’s Main Mini App. That profile “Launch app” experience is optional but recommended:

1. Open [@BotFather](https://t.me/BotFather)
2. Send `/mybots` → select this bot
3. **Bot Settings** → **Configure Mini App** (wording varies: Mini App / Main Mini App / Direct Mini App)
4. Set the Mini App URL to the same HTTPS origin as `MINI_APP_URL` (for example `https://YOUR_DOMAIN`)
5. Do not point this at `/api`

Anyone who can open the bot profile may see Launch App after this BotFather step. That is Telegram UX, not an authorization grant. The API still requires valid `initData` and `ALLOWED_USER_IDS`.

## Security

Access is enforced in two places:

* **Bot:** users not in `ALLOWED_USER_IDS` get `Access denied.` and no management controls.
* **API:** every protected endpoint requires validated Telegram Mini App `initData`. The frontend sends `Telegram.WebApp.initData` as `Authorization: tma <initData>` (or `X-Telegram-Init-Data`). The backend checks the HMAC using the bot token, extracts `user.id`, and rejects the request unless that id is in `ALLOWED_USER_IDS`.

`Telegram.WebApp.initDataUnsafe` is never trusted for authorization. A direct browser visit without valid `initData` cannot read shipment data. Missing/invalid `initData` returns HTTP 401. An authenticated Telegram user who is not allowlisted gets HTTP 403.

`ALLOWED_USER_IDS` must contain at least one integer. Spaces around commas are ignored. Invalid tokens abort startup. Empty/whitespace-only lists abort startup.

`DEV_AUTH_ENABLED=true` is ignored when `ENVIRONMENT=production` (the default). Unknown `ENVIRONMENT` values are treated as production. Dev auth logs a warning when it is actually active.

Production CORS defaults to empty (same-origin Mini App behind Nginx). Do not set `CORS_ORIGINS=*`.

Public endpoints: `GET /api/health` and static Mini App files. Shipment, account, team, reminder, history, dashboard, and lookup APIs require auth.

## Database backup and migration

The existing SQLite file is upgraded in place. IDs, notes, reminders, and status history are preserved.

**Safest first production upgrade:**

1. Stop `shipment-bot` and `shipment-api` so nothing is writing.
2. Copy the database (include WAL/SHM if you use `cp` while a process might still be open; `sqlite3 file.db '.backup backup.db'` is better).
3. Run schema migration once: `python -m database`
4. Start API, then bot.
5. Confirm `/api/health` and `/start`.

Helper: `./scripts/backup-db.sh` writes a timestamped copy next to the database (or to a path you pass). It prefers `sqlite3 .backup` and otherwise copies `-wal`/`-shm` companions. It never overwrites the live database file.

If you only `cp shipments.db` while services are running, you can miss WAL data. Stop the services or use `.backup`.

On connect (bot, API, or `python -m database`) the app:

* takes a process-level file lock (`DATABASE_PATH.migrate.lock`) then a SQLite `BEGIN EXCLUSIVE` so simultaneous bot+API startup cannot interleave WAL conversion or schema changes
* creates `accounts`, `client_teams`, and `bot_ui_sessions` if missing
* adds `account_id`, `client_team_id`, `box_weight`, `label_creation_date`, `scanned_in_date`, `delivered_date`
* copies legacy `expected_date` into `expected_delivery_date` when needed
* converts parseable EDD datetimes such as `2026-08-13T18:00:00Z` to `2026-08-13`
* moves unparseable free-text EDD (`tomorrow`, `Wednesday`, …) to `expected_date` and sets `expected_delivery_date` to NULL so the API never serializes junk into a date field
* does **not** invent account assignments for old rows (`account_id` stays null → UI shows “No account”)
* remaps legacy statuses `pending` / `working_on` to `standby`

Running migration twice is harmless. A failed migration rolls back and the process does not continue.

WAL mode, a 5s busy timeout (30s during migrate), and `foreign_keys=ON` are set on every connection in `Database.connect()`.

A new status value `delivered` is used for completion. Existing archived rows keep their previous status; the old Complete button used to archive, so those records appear under Archive rather than being rewritten as delivered.

Accounts and client teams are not hard-deleted. Creating a duplicate name is rejected (case-insensitive, trimmed). Referenced rows stay readable.

Account **total** = all non-hard-deleted shipments for that account, including delivered and archived. **Active** on the summary excludes delivered and archived.

Marking delivered sets `delivered` + `delivered_date` (today in `APP_TIMEZONE`) and does not archive. Completing twice keeps the original `delivered_date`. Changing status away from Delivered keeps `delivered_date` as historical data unless you clear it through a later deliberate edit (there is no automatic clear).

## Production deployment

Example layout (adjust to the machine you already use):

```
/opt/shipment-bot/app          # this repository
/opt/shipment-bot/app/.venv
/opt/shipment-bot/app/.env
/opt/shipment-bot/app/frontend/dist
```

If the current unit is still `shipment-bot.service` running only `python bot.py`, keep that unit for the bot/reminders and add `shipment-api.service` for FastAPI. Example units are in `deploy/`.

```bash
sudo cp deploy/shipment-bot.service /etc/systemd/system/
sudo cp deploy/shipment-api.service /etc/systemd/system/
# edit User, WorkingDirectory, and EnvironmentFile
sudo systemctl daemon-reload
sudo systemctl enable --now shipment-bot shipment-api
```

HTTPS is required for Telegram Mini Apps. Put Nginx (or another reverse proxy) in front with a real domain and certificate. See `deploy/nginx.conf.example`.

Checklist:

1. DNS A/AAAA record for your domain
2. TLS (Let’s Encrypt or existing certs)
3. Nginx: static `frontend/dist` + proxy `/api/` to `127.0.0.1:8000`
4. Set `MINI_APP_URL=https://YOUR_DOMAIN`
5. Restart bot and API
6. Confirm `/start` shows the shipment workspace (no Mini App URL required)
7. Confirm an unauthorized Telegram user cannot use the bot or load Mini App data

## Existing service migration

The previous app was a single long-polling bot with SQLite. Keep the same `DATABASE_PATH`. After pulling this version:

1. Stop the running bot (and API if already added)
2. Back up the SQLite file (`./scripts/backup-db.sh` or `sqlite3 "$DATABASE_PATH" ".backup backup.db"`)
3. Install new Python deps (`pip install -r requirements.txt`)
4. Build the frontend (`cd frontend && npm install && npm run build`)
5. Add optional env vars such as `MINI_APP_URL` (only if you still serve the Mini App) and `APP_TIMEZONE`. Leave `CORS_ORIGINS` empty in production.
6. Run `python -m database`
7. Start the API process, then the bot process

The Telegram bot workspace is the primary UI. The Mini App remains deployed and authenticated as before, but it is no longer required for daily shipment work.

Example units in `deploy/` run as `YOUR_LINUX_USER`, not root. If an older host still runs the bot as root, keep that only if you must; the new API+bot pair should use a dedicated user that can read/write `DATABASE_PATH` and `frontend/dist`.

## Development auth / testing

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Dev auth (`DEV_AUTH_ENABLED=true`) only works when `ENVIRONMENT` is not `production`. The API logs a warning when it is active.

## Statuses

Internal values are unchanged except for the new `delivered` status:

| Internal | Display | Group |
|---|---|---|
| `preparing` | Preparing | Working |
| `make_label` | Make Label | Working |
| `standby` | Standby | Working |
| `enroute` | En Route | In Transit |
| `out_for_delivery` | Out For Delivery | In Transit |
| `delivered` | Delivered | Completed |

Archive is independent of status (`archived = 1`). Completing a shipment sets `delivered` and `delivered_date` (today in `APP_TIMEZONE`) and does not archive it.

Operational shipment dates are `YYYY-MM-DD`. Reminders remain datetimes.

## Project layout

```
.
├── bot.py                 # Telegram bot workspace + reminder worker
├── run_api.py             # FastAPI / Uvicorn entry
├── api/                   # HTTP API, Telegram initData auth
├── bot_ui/                # Interactive Telegram workspace (keyboards, calendar, pickers)
├── database/              # SQLite schema, migrations, repositories
├── domain/                # status constants and grouping
├── frontend/              # React + TypeScript Mini App (optional)
├── handlers/              # bot command/callback handlers
├── services/              # reminder worker, serializers
├── deploy/                # systemd + Nginx examples
├── tests/
└── README.md
```
