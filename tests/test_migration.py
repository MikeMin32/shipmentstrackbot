from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from database.db import Database
from database.repository import ShipmentRepository


def _write_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            status TEXT NOT NULL,
            note TEXT,
            expected_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by INTEGER,
            archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_by INTEGER,
            changed_at TEXT NOT NULL
        );
        CREATE TABLE shipment_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL,
            remind_at TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            cancelled INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute(
        """
        INSERT INTO shipments (
            display_name, status, note, expected_date, created_at, updated_at, archived
        ) VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        ("DE: Oner", "enroute", "keep me", "2026-08-13T18:00:00Z", "t", "t"),
    )
    conn.execute(
        """
        INSERT INTO shipments (
            display_name, status, note, expected_date, created_at, updated_at, archived
        ) VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        ("CA: Durston", "preparing", "archived row", "Wednesday", "t", "t"),
    )
    conn.execute(
        """
        INSERT INTO status_history (shipment_id, old_status, new_status, changed_by, changed_at)
        VALUES (1, NULL, 'enroute', 111, 't')
        """
    )
    conn.execute(
        """
        INSERT INTO shipment_reminders (
            shipment_id, remind_at, created_by, created_at, sent_at, cancelled
        ) VALUES (1, '2026-09-10T15:00:00Z', 111, 't', NULL, 0)
        """
    )
    conn.execute(
        """
        INSERT INTO shipments (
            display_name, status, note, expected_date, created_at, updated_at, archived
        ) VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        ("DE: Pending", "pending", "legacy status", "next Friday", "t", "t"),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_legacy_edd_datetime_migrates_to_date(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _write_legacy_db(db_path)
    db = Database(db_path)
    await db.connect()
    try:
        repo = ShipmentRepository(db)
        shipment = await repo.get_by_id(1)
        assert shipment is not None
        assert shipment["country"] == "DE"
        assert shipment["clone_name"] == "Oner"
        assert shipment["name"] in {None, ""}
        assert shipment["expected_delivery_date"] == "2026-08-13"
        assert shipment["note"] == "keep me"
        assert shipment["account_id"] is not None
        assert shipment["account_name"] == "Oner"
        archived = await repo.get_by_id(2)
        assert archived is not None
        assert archived["archived"] == 1
        assert archived["expected_delivery_date"] is None
        assert archived["expected_date"] == "Wednesday"
        reminder = await repo.get_active_reminder(1)
        assert reminder is not None
        history = await repo.list_history(1)
        assert history
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_connect_migrates_once(tmp_path: Path) -> None:
    db_path = tmp_path / "race.db"
    _write_legacy_db(db_path)

    async def boot() -> Database:
        db = Database(db_path)
        await db.connect()
        return db

    first, second = await asyncio.gather(boot(), boot())
    try:
        for db in (first, second):
            repo = ShipmentRepository(db)
            row = await repo.get_by_id(1)
            assert row is not None
            assert row["expected_delivery_date"] == "2026-08-13"
            bad = await repo.get_by_id(2)
            assert bad is not None
            assert bad["expected_delivery_date"] is None
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_malformed_edd_is_not_treated_as_iso_date(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-dates.db"
    _write_legacy_db(db_path)
    db = Database(db_path)
    await db.connect()
    try:
        repo = ShipmentRepository(db)
        await repo.migrate_legacy_statuses()
        ok = await repo.get_by_id(1)
        assert ok is not None
        assert ok["expected_delivery_date"] == "2026-08-13"
        assert ok["note"] == "keep me"
        assert ok["account_name"] == "Oner"
        assert ok["clone_name"] == "Oner"
        malformed = await repo.get_by_id(2)
        assert malformed is not None
        assert malformed["expected_delivery_date"] is None
        assert malformed["archived"] == 1
        history = await repo.list_history(1)
        assert history
        reminder = await repo.get_active_reminder(1)
        assert reminder is not None
        pending = await repo.get_by_id(3)
        assert pending is not None
        assert pending["status"] == "standby"
        assert pending["expected_delivery_date"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_existing_sessions_table_gains_needs_reposition(tmp_path: Path) -> None:
    db_path = tmp_path / "old-sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE bot_ui_sessions (
            telegram_user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            current_view TEXT NOT NULL DEFAULT 'home',
            updated_at TEXT NOT NULL
        );
        INSERT INTO bot_ui_sessions (
            telegram_user_id, chat_id, message_id, current_view, updated_at
        ) VALUES (111, 222, 333, 'home', 't');
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    await db.connect()
    try:
        cols = await db._table_columns("bot_ui_sessions")
        assert "needs_reposition" in cols
        cursor = await db.connection.execute(
            "SELECT needs_reposition FROM bot_ui_sessions WHERE telegram_user_id = 111"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert int(row["needs_reposition"]) == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_wal_busy_timeout_and_foreign_keys(tmp_path: Path) -> None:
    db = Database(tmp_path / "pragma.db")
    await db.connect()
    try:
        journal = await (await db.connection.execute("PRAGMA journal_mode")).fetchone()
        timeout = await (await db.connection.execute("PRAGMA busy_timeout")).fetchone()
        fks = await (await db.connection.execute("PRAGMA foreign_keys")).fetchone()
        tables = await (
            await db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_ui_sessions'"
            )
        ).fetchone()
        assert str(journal[0]).lower() == "wal"
        assert int(timeout[0]) == 5_000
        assert int(fks[0]) == 1
        assert tables is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_read_and_write(tmp_path: Path) -> None:
    from database.entities import AccountRepository

    db_path = tmp_path / "concurrent.db"
    writer = Database(db_path)
    reader = Database(db_path)
    await writer.connect()
    await reader.connect()
    try:
        account = await AccountRepository(writer).create("Concurrent")
        repo_w = ShipmentRepository(writer)
        repo_r = ShipmentRepository(reader)
        shipment = await repo_w.create(
            country="DE",
            clone_name="Oner",
            status="preparing",
            created_by=111,
            account_id=account["id"],
            require_account=True,
        )

        async def write_loop() -> None:
            for status in ("enroute", "preparing", "standby", "out_for_delivery"):
                updated = await repo_w.update_status(shipment["id"], status, changed_by=111)
                assert updated is not None

        async def read_loop() -> None:
            for _ in range(12):
                row = await repo_r.get_by_id(shipment["id"])
                assert row is not None
                assert row["id"] == shipment["id"]

        await asyncio.gather(write_loop(), read_loop())
        final = await repo_r.get_by_id(shipment["id"])
        assert final is not None
        assert final["status"] == "out_for_delivery"
    finally:
        await writer.close()
        await reader.close()


@pytest.mark.asyncio
async def test_legacy_clone_becomes_account_not_name(tmp_path: Path) -> None:
    db_path = tmp_path / "clone-account.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT,
            clone_name TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            account_id INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO accounts (name, created_at, updated_at, archived) VALUES ('Existing Co', 't', 't', 0)"
    )
    conn.execute(
        """
        INSERT INTO shipments (country, clone_name, status, created_at, updated_at, archived, account_id)
        VALUES
            ('DE', 'Oner', 'enroute', 't', 't', 0, NULL),
            ('DE', ' oner ', 'preparing', 't', 't', 0, NULL),
            ('CA', 'Durston', 'preparing', 't', 't', 0, NULL),
            ('IT', 'ShouldStay', 'preparing', 't', 't', 0, 1)
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    await db.connect()
    try:
        repo = ShipmentRepository(db)
        first = await repo.get_by_id(1)
        second = await repo.get_by_id(2)
        third = await repo.get_by_id(3)
        kept = await repo.get_by_id(4)
        assert first is not None and second is not None and third is not None and kept is not None
        assert first["account_name"] == "Oner"
        assert second["account_id"] == first["account_id"]
        assert first["name"] in {None, ""}
        assert first["clone_name"] == "Oner"
        assert third["account_name"] == "Durston"
        assert kept["account_id"] == 1
        assert kept["account_name"] == "Existing Co"
        assert kept["clone_name"] == "ShouldStay"

        again = await db.migrate_legacy_clone_to_accounts()
        assert again == 0
        cursor = await db.connection.execute("SELECT COUNT(*) AS cnt FROM accounts WHERE archived = 0")
        row = await cursor.fetchone()
        assert int(row["cnt"]) == 3
    finally:
        await db.close()


def _write_box_weight_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE shipments (
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
            box_weight REAL,
            label_creation_date TEXT,
            scanned_in_date TEXT,
            delivered_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by INTEGER,
            archived INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute(
        """
        INSERT INTO shipments (
            country, clone_name, name, display_name, status,
            box_weight, created_at, updated_at, archived
        ) VALUES
            ('DE', 'Oner', 'Oner Active', 'DE: Oner', 'enroute', 5, 't', 't', 0),
            ('CA', 'Durston', 'Durston', 'CA: Durston', 'preparing', NULL, 't', 't', 0)
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_box_weight_migrates_to_unit_quantity(tmp_path: Path) -> None:
    db_path = tmp_path / "box-weight.db"
    _write_box_weight_db(db_path)

    db = Database(db_path)
    await db.connect()
    try:
        cols = await db._table_columns("shipments")
        assert "unit_quantity" in cols
        assert "box_weight" not in cols
        repo = ShipmentRepository(db)
        first = await repo.get_by_id(1)
        second = await repo.get_by_id(2)
        assert first is not None
        assert first["unit_quantity"] == 5
        assert "box_weight" not in first
        assert second is not None
        assert second["unit_quantity"] is None
    finally:
        await db.close()

    again = Database(db_path)
    await again.connect()
    try:
        cols = await again._table_columns("shipments")
        assert "unit_quantity" in cols
        assert "box_weight" not in cols
        repo = ShipmentRepository(again)
        first = await repo.get_by_id(1)
        assert first is not None
        assert first["unit_quantity"] == 5
        updated = await repo.update_fields(1, unit_quantity=8.4)
        assert updated is not None
        assert updated["unit_quantity"] == 8.4
        assert "box_weight" not in updated
    finally:
        await again.close()
