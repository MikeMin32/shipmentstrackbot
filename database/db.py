"""SQLite connection helpers and idempotent migrations."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT,
    clone_name TEXT,
    display_name TEXT,
    status TEXT NOT NULL,
    note TEXT,
    expected_date TEXT,
    expected_delivery_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by INTEGER,
    archived INTEGER NOT NULL DEFAULT 0
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
"""


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
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()
        logger.info("Database ready at %s", self.path)

    async def _table_columns(self, table: str) -> set[str]:
        cursor = await self.connection.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        return {row["name"] for row in rows}

    async def _migrate(self) -> None:
        cols = await self._table_columns("shipments")

        alter_statements: list[str] = []
        if "country" not in cols:
            alter_statements.append("ALTER TABLE shipments ADD COLUMN country TEXT")
        if "clone_name" not in cols:
            alter_statements.append("ALTER TABLE shipments ADD COLUMN clone_name TEXT")
        if "expected_delivery_date" not in cols:
            alter_statements.append(
                "ALTER TABLE shipments ADD COLUMN expected_delivery_date TEXT"
            )
        if "display_name" not in cols:
            alter_statements.append("ALTER TABLE shipments ADD COLUMN display_name TEXT")
        if "expected_date" not in cols:
            alter_statements.append("ALTER TABLE shipments ADD COLUMN expected_date TEXT")

        for sql in alter_statements:
            await self.connection.execute(sql)
            logger.info("Applied schema change: %s", sql)

        # Copy legacy EDD values once
        await self.connection.execute(
            """
            UPDATE shipments
            SET expected_delivery_date = expected_date
            WHERE (expected_delivery_date IS NULL OR expected_delivery_date = '')
              AND expected_date IS NOT NULL
              AND expected_date != ''
            """
        )

        # Split legacy display_name into country/clone where missing
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

        # Keep display_name in sync for older tooling / fallbacks
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

        # Normalize already-valid datetime EDD values to ISO UTC; leave free-text alone
        cursor = await self.connection.execute(
            """
            SELECT id, expected_delivery_date
            FROM shipments
            WHERE expected_delivery_date IS NOT NULL
              AND expected_delivery_date != ''
            """
        )
        from utils.timefmt import normalize_stored_utc, try_parse_stored

        for row in await cursor.fetchall():
            raw = row["expected_delivery_date"]
            if try_parse_stored(raw) is None:
                continue
            normalized = normalize_stored_utc(raw)
            if normalized and normalized != raw:
                await self.connection.execute(
                    """
                    UPDATE shipments
                    SET expected_delivery_date = ?, expected_date = ?
                    WHERE id = ?
                    """,
                    (normalized, normalized, row["id"]),
                )

        # Indexes that depend on migrated columns
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shipments_country_clone
                ON shipments(country, clone_name)
            """
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")
