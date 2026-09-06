"""SQLite connection helpers and exclusive, idempotent migrations."""

from __future__ import annotations

import asyncio
import fcntl
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, TextIO

import aiosqlite

from utils.dates import extract_date_component

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS client_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT,
    clone_name TEXT,
    name TEXT,
    display_name TEXT,
    status TEXT NOT NULL,
    note TEXT,
    expected_date TEXT,
    expected_delivery_date TEXT,
    account_id INTEGER,
    client_team_id INTEGER,
    unit_quantity REAL,
    edd_48h_sent_for TEXT,
    edd_24h_sent_for TEXT,
    label_creation_date TEXT,
    scanned_in_date TEXT,
    delivered_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by INTEGER,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (client_team_id) REFERENCES client_teams(id)
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by INTEGER,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipments(id)
);

CREATE TABLE IF NOT EXISTS shipment_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL,
    remind_at TEXT NOT NULL,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    cancelled INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (shipment_id) REFERENCES shipments(id)
);

CREATE INDEX IF NOT EXISTS idx_shipments_archived_status
    ON shipments(archived, status);

CREATE INDEX IF NOT EXISTS idx_status_history_shipment
    ON status_history(shipment_id);

CREATE INDEX IF NOT EXISTS idx_reminders_due
    ON shipment_reminders(cancelled, sent_at, remind_at);

CREATE INDEX IF NOT EXISTS idx_accounts_name
    ON accounts(name);

CREATE INDEX IF NOT EXISTS idx_client_teams_name
    ON client_teams(name);

CREATE TABLE IF NOT EXISTS bot_ui_sessions (
    telegram_user_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    current_view TEXT NOT NULL DEFAULT 'home',
    updated_at TEXT NOT NULL
);
"""

SCHEMA_STATEMENTS: tuple[str, ...] = tuple(
    statement.strip()
    for statement in SCHEMA.split(";")
    if statement.strip()
)

MIGRATE_BUSY_TIMEOUT_MS = 30_000
RUNTIME_BUSY_TIMEOUT_MS = 5_000

NEW_SHIPMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("country", "TEXT"),
    ("clone_name", "TEXT"),
    ("expected_delivery_date", "TEXT"),
    ("display_name", "TEXT"),
    ("expected_date", "TEXT"),
    ("account_id", "INTEGER"),
    ("client_team_id", "INTEGER"),
    ("unit_quantity", "REAL"),
    ("edd_48h_sent_for", "TEXT"),
    ("edd_24h_sent_for", "TEXT"),
    ("label_creation_date", "TEXT"),
    ("scanned_in_date", "TEXT"),
    ("delivered_date", "TEXT"),
    ("name", "TEXT"),
)


def _migration_now() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M")


def parse_display_name(value: str | None) -> tuple[str, str]:
    """Split 'DE: Oner' into country/clone. Unparseable values stay in clone_name."""
    raw = (value or "").strip()
    if not raw:
        return "", ""
    if ":" not in raw:
        return "", raw
    left, right = raw.split(":", 1)
    country = left.strip()
    clone = right.strip()
    if not country and not clone:
        return "", raw
    return country, clone


def _acquire_migrate_lock(lock_path: Path) -> TextIO:
    handle = lock_path.open("a", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release_migrate_lock(handle: IO[str]) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(
            self.path,
            timeout=MIGRATE_BUSY_TIMEOUT_MS / 1000,
        )
        self._conn.row_factory = aiosqlite.Row
        # Busy timeout must be set before WAL conversion or migrate; default is 0
        # for some lock types and concurrent bot startup would fail immediately.
        await self._conn.execute(f"PRAGMA busy_timeout = {MIGRATE_BUSY_TIMEOUT_MS}")
        await self._conn.execute("PRAGMA foreign_keys = ON")
        lock_path = Path(str(self.path) + ".migrate.lock")
        lock_handle = await asyncio.to_thread(_acquire_migrate_lock, lock_path)
        try:
            await self._conn.execute("PRAGMA journal_mode = WAL")
            await self._migrate_with_lock()
        finally:
            await asyncio.to_thread(_release_migrate_lock, lock_handle)
        await self._conn.execute(f"PRAGMA busy_timeout = {RUNTIME_BUSY_TIMEOUT_MS}")
        logger.info("Database ready at %s", self.path)

    async def _migrate_with_lock(self) -> None:
        """Serialize schema upgrades so only one process migrates at a time."""
        await self.connection.commit()
        await self.connection.execute("BEGIN EXCLUSIVE")
        try:
            for statement in SCHEMA_STATEMENTS:
                await self.connection.execute(statement)
            await self._migrate()
            await self.connection.commit()
        except Exception:
            logger.exception("Database migration failed; rolling back")
            try:
                await self.connection.rollback()
            except Exception:
                logger.exception("Rollback after failed migration also failed")
            raise

    async def _table_columns(self, table: str) -> set[str]:
        cursor = await self.connection.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        return {row["name"] for row in rows}

    async def _table_exists(self, table: str) -> bool:
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
        return await cursor.fetchone() is not None

    async def _add_column(self, name: str, col_type: str) -> None:
        sql = f"ALTER TABLE shipments ADD COLUMN {name} {col_type}"
        try:
            await self.connection.execute(sql)
            logger.info("Applied schema change: %s", sql)
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                logger.info("Column already present: %s", name)
                return
            raise

    async def _migrate_box_weight_to_unit_quantity(self) -> None:
        """Copy leftover box_weight values into unit_quantity, then drop box_weight.

        Safe on fresh databases (no box_weight), already-migrated databases, and
        databases that still have the old column. Existing unit_quantity values
        are never overwritten.
        """
        cols = await self._table_columns("shipments")
        if "unit_quantity" not in cols:
            await self._add_column("unit_quantity", "REAL")
            cols = await self._table_columns("shipments")

        if "box_weight" not in cols:
            return

        cursor = await self.connection.execute(
            """
            UPDATE shipments
            SET unit_quantity = box_weight
            WHERE unit_quantity IS NULL
              AND box_weight IS NOT NULL
            """
        )
        copied = cursor.rowcount or 0
        if copied:
            logger.info("Copied box_weight into unit_quantity for %s shipment(s)", copied)

        try:
            await self.connection.execute("ALTER TABLE shipments DROP COLUMN box_weight")
            logger.info("Dropped leftover shipments.box_weight column")
        except aiosqlite.OperationalError as exc:
            # SQLite < 3.35 cannot DROP COLUMN. Leave the unused column in place;
            # application code reads and writes unit_quantity only.
            logger.info("Could not drop shipments.box_weight (%s); column left unused", exc)

    async def _migrate(self) -> None:
        cols = await self._table_columns("shipments")
        for name, col_type in NEW_SHIPMENT_COLUMNS:
            if name not in cols:
                await self._add_column(name, col_type)

        await self._migrate_box_weight_to_unit_quantity()

        # Copy legacy EDD into expected_delivery_date when that column is empty.
        await self.connection.execute(
            """
            UPDATE shipments
            SET expected_delivery_date = expected_date
            WHERE (expected_delivery_date IS NULL OR expected_delivery_date = '')
              AND expected_date IS NOT NULL
              AND expected_date != ''
            """
        )

        cursor = await self.connection.execute(
            """
            SELECT id, display_name, country, clone_name
            FROM shipments
            WHERE (country IS NULL OR country = '')
              AND (clone_name IS NULL OR clone_name = '')
            """
        )
        rows = await cursor.fetchall()
        migrated = 0
        for row in rows:
            country, clone = parse_display_name(row["display_name"])
            if not country and not clone:
                clone = (row["display_name"] or "").strip() or f"#{row['id']}"
            await self.connection.execute(
                """
                UPDATE shipments
                SET country = ?, clone_name = ?
                WHERE id = ?
                """,
                (country, clone, row["id"]),
            )
            migrated += 1
        if migrated:
            logger.info("Migrated country/clone_name for %s shipment(s)", migrated)

        await self.connection.execute(
            """
            UPDATE shipments
            SET display_name =
                CASE
                    WHEN country IS NOT NULL AND country != ''
                     AND clone_name IS NOT NULL AND clone_name != ''
                        THEN country || ': ' || clone_name
                    WHEN clone_name IS NOT NULL AND clone_name != ''
                        THEN clone_name
                    WHEN country IS NOT NULL AND country != ''
                        THEN country
                    ELSE COALESCE(display_name, '')
                END
            WHERE country IS NOT NULL OR clone_name IS NOT NULL
            """
        )

        # Canonical date column is expected_delivery_date (YYYY-MM-DD).
        # Unparseable free-text is kept in expected_date and cleared from EDD
        # so date fields never treat free-text as an ISO date.
        cursor = await self.connection.execute(
            """
            SELECT id, expected_delivery_date, expected_date
            FROM shipments
            WHERE (expected_delivery_date IS NOT NULL AND expected_delivery_date != '')
               OR (expected_date IS NOT NULL AND expected_date != '')
            """
        )
        date_migrated = 0
        cleared = 0
        for row in await cursor.fetchall():
            raw_edd = row["expected_delivery_date"]
            raw_legacy = row["expected_date"]
            extracted = extract_date_component(raw_edd) or extract_date_component(raw_legacy)
            if extracted:
                if extracted != raw_edd:
                    await self.connection.execute(
                        """
                        UPDATE shipments
                        SET expected_delivery_date = ?
                        WHERE id = ?
                        """,
                        (extracted, row["id"]),
                    )
                    date_migrated += 1
                continue
            preserve = (raw_legacy or raw_edd or "").strip() or None
            await self.connection.execute(
                """
                UPDATE shipments
                SET expected_delivery_date = NULL,
                    expected_date = ?
                WHERE id = ?
                """,
                (preserve, row["id"]),
            )
            if raw_edd:
                cleared += 1
        if date_migrated:
            logger.info(
                "Migrated %s expected_delivery_date value(s) to YYYY-MM-DD",
                date_migrated,
            )
        if cleared:
            logger.info(
                "Moved %s unparseable EDD value(s) to expected_date and cleared expected_delivery_date",
                cleared,
            )

        assigned = await self.migrate_legacy_clone_to_accounts()
        if assigned:
            logger.info(
                "Assigned accounts from legacy clone values for %s shipment(s)",
                assigned,
            )

        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_shipments_country_clone ON shipments(country, clone_name)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_account_id ON shipments(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_client_team_id ON shipments(client_team_id)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_expected_delivery_date ON shipments(expected_delivery_date)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_archived ON shipments(archived)",
        ):
            await self.connection.execute(sql)

    async def migrate_legacy_clone_to_accounts(self) -> int:
        """Assign accounts from legacy clone/company values. Idempotent.

        Only fills NULL account_id. Does not overwrite existing accounts
        and does not copy clone values into the shipment name field.
        """
        cursor = await self.connection.execute(
            """
            SELECT id, clone_name
            FROM shipments
            WHERE account_id IS NULL
              AND clone_name IS NOT NULL
              AND TRIM(clone_name) != ''
            """
        )
        rows = await cursor.fetchall()
        assigned = 0
        now = _migration_now()
        for row in rows:
            company = (row["clone_name"] or "").strip()
            if not company:
                continue
            account_id = await self._get_or_create_account_id(company, now)
            await self.connection.execute(
                """
                UPDATE shipments
                SET account_id = ?
                WHERE id = ? AND account_id IS NULL
                """,
                (account_id, row["id"]),
            )
            assigned += 1
        return assigned

    async def _get_or_create_account_id(self, name: str, now: str) -> int:
        cursor = await self.connection.execute(
            """
            SELECT id, archived
            FROM accounts
            WHERE name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (name,),
        )
        existing = await cursor.fetchone()
        if existing is not None:
            if existing["archived"]:
                await self.connection.execute(
                    "UPDATE accounts SET archived = 0, updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
            return int(existing["id"])
        cursor = await self.connection.execute(
            """
            INSERT INTO accounts (name, created_at, updated_at, archived)
            VALUES (?, ?, ?, 0)
            """,
            (name, now, now),
        )
        return int(cursor.lastrowid)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")
