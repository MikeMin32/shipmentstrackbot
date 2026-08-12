"""Shipment persistence, status history, and reminders."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from database.db import Database
from utils.formatting import DEFAULT_STATUS, STATUSES
from utils.timefmt import now_utc, normalize_stored_utc, to_store, try_parse_stored

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M")


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _compose_display_name(country: str, clone_name: str) -> str:
    country = country.strip()
    clone_name = clone_name.strip()
    if country and clone_name:
        return f"{country}: {clone_name}"
    return clone_name or country


# Initial list matching the previous chat-based tracker
SEED_SHIPMENTS: tuple[dict[str, str | None], ...] = (
    {
        "country": "DE",
        "clone_name": "Oner",
        "status": "enroute",
        "expected_delivery_date": "2026-08-13T18:00:00Z",
    },
    {
        "country": "CA",
        "clone_name": "Durston",
        "status": "preparing",
        "expected_delivery_date": "2026-08-18T12:00:00Z",
    },
    {
        "country": "DE",
        "clone_name": "Oner",
        "status": "preparing",
        "expected_delivery_date": "2026-08-20T12:00:00Z",
    },
    {
        "country": "ATL",
        "clone_name": "Auto",
        "status": "preparing",
        "expected_delivery_date": "2026-08-19T12:00:00Z",
    },
    {
        "country": "LA",
        "clone_name": "Le Bon",
        "status": "standby",
        "expected_delivery_date": "2026-08-25T12:00:00Z",
    },
    {
        "country": "DE",
        "clone_name": "Blickle",
        "status": "standby",
        "expected_delivery_date": "2026-08-26T12:00:00Z",
    },
)

LEGACY_STATUS_MAP: dict[str, str] = {
    "pending": "standby",
    "working_on": "standby",
}


class ShipmentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def count_all(self) -> int:
        cursor = await self.db.connection.execute("SELECT COUNT(*) AS cnt FROM shipments")
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def migrate_legacy_statuses(self) -> int:
        total = 0
        for old, new in LEGACY_STATUS_MAP.items():
            cursor = await self.db.connection.execute(
                "UPDATE shipments SET status = ? WHERE status = ?",
                (new, old),
            )
            total += cursor.rowcount or 0
            await self.db.connection.execute(
                "UPDATE status_history SET old_status = ? WHERE old_status = ?",
                (new, old),
            )
            await self.db.connection.execute(
                "UPDATE status_history SET new_status = ? WHERE new_status = ?",
                (new, old),
            )
        await self.db.connection.commit()
        if total:
            logger.info("Migrated %s shipment row(s) from legacy statuses to standby", total)
        return total

    async def seed_if_empty(self) -> int:
        if await self.count_all() > 0:
            return 0

        for item in SEED_SHIPMENTS:
            await self.create(
                country=str(item["country"]),
                clone_name=str(item["clone_name"]),
                status=str(item["status"]),
                expected_delivery_date=item["expected_delivery_date"],
                created_by=None,
            )
        logger.info("Seeded %s initial shipments", len(SEED_SHIPMENTS))
        return len(SEED_SHIPMENTS)

    async def create(
        self,
        *,
        country: str,
        clone_name: str,
        status: str = DEFAULT_STATUS,
        created_by: int | None = None,
        note: str | None = None,
        expected_delivery_date: str,
    ) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"Invalid status: {status}")

        country = country.strip()
        clone_name = clone_name.strip()
        edd = normalize_stored_utc(expected_delivery_date)
        if not edd or try_parse_stored(edd) is None:
            raise ValueError("expected_delivery_date must be a valid UTC datetime")
        display_name = _compose_display_name(country, clone_name)
        now = _now()
        try:
            cursor = await self.db.connection.execute(
                """
                INSERT INTO shipments (
                    country, clone_name, display_name, status, note,
                    expected_date, expected_delivery_date,
                    created_at, updated_at, created_by, archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    country,
                    clone_name,
                    display_name,
                    status,
                    note,
                    edd,
                    edd,
                    now,
                    now,
                    created_by,
                ),
            )
            shipment_id = cursor.lastrowid
            await self.db.connection.execute(
                """
                INSERT INTO status_history (
                    shipment_id, old_status, new_status, changed_by, changed_at
                ) VALUES (?, NULL, ?, ?, ?)
                """,
                (shipment_id, status, created_by, now),
            )
            await self.db.connection.commit()
            logger.info(
                "Shipment created id=%s country=%r clone=%r status=%s by=%s",
                shipment_id,
                country,
                clone_name,
                status,
                created_by,
            )
            shipment = await self.get_by_id(shipment_id)
            assert shipment is not None
            return shipment
        except Exception:
            logger.exception(
                "Failed to create shipment country=%r clone=%r", country, clone_name
            )
            raise

    async def get_by_id(self, shipment_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            "SELECT * FROM shipments WHERE id = ?",
            (shipment_id,),
        )
        return _row_to_dict(await cursor.fetchone())

    async def list_active(self) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT * FROM shipments
            WHERE archived = 0
            ORDER BY
                CASE WHEN status = 'enroute' THEN 0 ELSE 1 END,
                CASE status
                    WHEN 'enroute' THEN 0
                    WHEN 'preparing' THEN 1
                    WHEN 'make_label' THEN 2
                    WHEN 'out_for_delivery' THEN 3
                    WHEN 'standby' THEN 4
                    ELSE 5
                END,
                id ASC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT * FROM shipments
            WHERE archived = 0 AND status = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (status,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def count_by_status(self) -> dict[str, int]:
        cursor = await self.db.connection.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM shipments
            WHERE archived = 0
            GROUP BY status
            """
        )
        rows = await cursor.fetchall()
        counts = {status: 0 for status in STATUSES}
        for row in rows:
            status = row["status"]
            if status in counts:
                counts[status] = row["cnt"]
        return counts

    async def search(self, query: str) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        cursor = await self.db.connection.execute(
            """
            SELECT * FROM shipments
            WHERE archived = 0
              AND (
                    country LIKE ? COLLATE NOCASE
                 OR clone_name LIKE ? COLLATE NOCASE
                 OR display_name LIKE ? COLLATE NOCASE
                 OR (COALESCE(country, '') || ' : ' || COALESCE(clone_name, ''))
                        LIKE ? COLLATE NOCASE
              )
            ORDER BY updated_at DESC, id DESC
            LIMIT 50
            """,
            (pattern, pattern, pattern, pattern),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_status(
        self,
        shipment_id: int,
        new_status: str,
        *,
        changed_by: int | None = None,
    ) -> dict[str, Any] | None:
        if new_status not in STATUSES:
            raise ValueError(f"Invalid status: {new_status}")

        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            return None

        old_status = shipment["status"]
        if old_status == new_status:
            return shipment

        now = _now()
        try:
            await self.db.connection.execute(
                """
                UPDATE shipments
                SET status = ?, updated_at = ?
                WHERE id = ? AND archived = 0
                """,
                (new_status, now, shipment_id),
            )
            await self.db.connection.execute(
                """
                INSERT INTO status_history (
                    shipment_id, old_status, new_status, changed_by, changed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (shipment_id, old_status, new_status, changed_by, now),
            )
            await self.db.connection.commit()
            logger.info(
                "Status changed id=%s %s -> %s by=%s",
                shipment_id,
                old_status,
                new_status,
                changed_by,
            )
            return await self.get_by_id(shipment_id)
        except Exception:
            logger.exception("Failed to update status id=%s", shipment_id)
            raise

    async def update_country(
        self,
        shipment_id: int,
        country: str,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            return None

        country = country.strip()
        clone_name = (shipment.get("clone_name") or "").strip()
        display_name = _compose_display_name(country, clone_name)
        now = _now()
        await self.db.connection.execute(
            """
            UPDATE shipments
            SET country = ?, display_name = ?, updated_at = ?
            WHERE id = ? AND archived = 0
            """,
            (country, display_name, now, shipment_id),
        )
        await self.db.connection.commit()
        return await self.get_by_id(shipment_id)

    async def update_clone_name(
        self,
        shipment_id: int,
        clone_name: str,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            return None

        clone_name = clone_name.strip()
        country = (shipment.get("country") or "").strip()
        display_name = _compose_display_name(country, clone_name)
        now = _now()
        await self.db.connection.execute(
            """
            UPDATE shipments
            SET clone_name = ?, display_name = ?, updated_at = ?
            WHERE id = ? AND archived = 0
            """,
            (clone_name, display_name, now, shipment_id),
        )
        await self.db.connection.commit()
        return await self.get_by_id(shipment_id)

    async def update_edd(
        self,
        shipment_id: int,
        expected_delivery_date: str,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            return None

        edd = normalize_stored_utc(expected_delivery_date)
        if not edd or try_parse_stored(edd) is None:
            raise ValueError("expected_delivery_date must be a valid UTC datetime")

        now = _now()
        await self.db.connection.execute(
            """
            UPDATE shipments
            SET expected_delivery_date = ?,
                expected_date = ?,
                updated_at = ?
            WHERE id = ? AND archived = 0
            """,
            (edd, edd, now, shipment_id),
        )
        await self.db.connection.commit()
        return await self.get_by_id(shipment_id)

    async def update_note(
        self,
        shipment_id: int,
        note: str | None,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            return None

        now = _now()
        await self.db.connection.execute(
            """
            UPDATE shipments
            SET note = ?, updated_at = ?
            WHERE id = ? AND archived = 0
            """,
            (note, now, shipment_id),
        )
        await self.db.connection.commit()
        return await self.get_by_id(shipment_id)

    async def archive(
        self,
        shipment_id: int,
        *,
        changed_by: int | None = None,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None:
            return None
        if shipment["archived"]:
            return shipment

        now = _now()
        try:
            await self.db.connection.execute(
                """
                UPDATE shipments
                SET archived = 1, updated_at = ?
                WHERE id = ?
                """,
                (now, shipment_id),
            )
            await self.cancel_active_reminders(shipment_id)
            await self.db.connection.commit()
            logger.info("Shipment archived id=%s by=%s", shipment_id, changed_by)
            return await self.get_by_id(shipment_id)
        except Exception:
            logger.exception("Failed to archive shipment id=%s", shipment_id)
            raise

    # --- Reminders ---------------------------------------------------------

    async def get_active_reminder(self, shipment_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            """
            SELECT * FROM shipment_reminders
            WHERE shipment_id = ?
              AND cancelled = 0
              AND sent_at IS NULL
            ORDER BY remind_at ASC
            LIMIT 1
            """,
            (shipment_id,),
        )
        return _row_to_dict(await cursor.fetchone())

    async def cancel_active_reminders(self, shipment_id: int) -> int:
        cursor = await self.db.connection.execute(
            """
            UPDATE shipment_reminders
            SET cancelled = 1
            WHERE shipment_id = ?
              AND cancelled = 0
              AND sent_at IS NULL
            """,
            (shipment_id,),
        )
        return cursor.rowcount or 0

    async def set_reminder(
        self,
        shipment_id: int,
        remind_at: datetime,
        *,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            raise ValueError("Shipment not available")

        await self.cancel_active_reminders(shipment_id)
        stored = to_store(remind_at)
        created_at = _now()
        cursor = await self.db.connection.execute(
            """
            INSERT INTO shipment_reminders (
                shipment_id, remind_at, created_by, created_at, sent_at, cancelled
            ) VALUES (?, ?, ?, ?, NULL, 0)
            """,
            (shipment_id, stored, created_by, created_at),
        )
        await self.db.connection.commit()
        reminder_id = cursor.lastrowid
        logger.info(
            "Reminder set id=%s shipment_id=%s remind_at=%s by=%s",
            reminder_id,
            shipment_id,
            stored,
            created_by,
        )
        reminder = await self.get_reminder_by_id(reminder_id)
        assert reminder is not None
        return reminder

    async def get_reminder_by_id(self, reminder_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            "SELECT * FROM shipment_reminders WHERE id = ?",
            (reminder_id,),
        )
        return _row_to_dict(await cursor.fetchone())

    async def due_reminders(
        self,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return unsent reminders that are due using aware UTC comparisons."""
        now_dt = now or now_utc()
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = now_dt.astimezone(timezone.utc)

        cursor = await self.db.connection.execute(
            """
            SELECT r.*,
                   s.country, s.clone_name, s.display_name, s.status,
                   s.expected_delivery_date, s.expected_date, s.archived
            FROM shipment_reminders r
            JOIN shipments s ON s.id = r.shipment_id
            WHERE r.cancelled = 0
              AND r.sent_at IS NULL
              AND s.archived = 0
            ORDER BY r.remind_at ASC, r.id ASC
            """
        )
        rows = await cursor.fetchall()
        due: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            remind_at = try_parse_stored(item.get("remind_at"))
            if remind_at is not None and remind_at <= now_dt:
                due.append(item)
        return due

    async def mark_reminder_sent(self, reminder_id: int) -> bool:
        """Mark sent if still unsent/uncancelled. Returns True if this call won the race."""
        sent_at = _now()
        cursor = await self.db.connection.execute(
            """
            UPDATE shipment_reminders
            SET sent_at = ?
            WHERE id = ?
              AND cancelled = 0
              AND sent_at IS NULL
            """,
            (sent_at, reminder_id),
        )
        await self.db.connection.commit()
        return (cursor.rowcount or 0) > 0
