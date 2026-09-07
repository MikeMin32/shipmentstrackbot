"""Shipment persistence, status history, and reminders."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

from database.db import Database
from domain.status import (
    ACTIVE_STATUSES,
    DEFAULT_STATUS,
    DELIVERED_STATUS,
    IN_TRANSIT_STATUSES,
    STATUSES,
    WORKING_STATUSES,
)
from utils.dates import coerce_iso_date, extract_date_component
from utils.timefmt import now_utc, to_store, try_parse_stored

logger = logging.getLogger(__name__)

MAX_COUNTRY_LEN = 40
MAX_CLONE_LEN = 80
MAX_SHIPMENT_NAME_LEN = 80
MAX_NOTE_LEN = 500
MAX_UNIT_QUANTITY = 10000.0
SHIPMENT_SELECT = """
SELECT
    s.*,
    a.name AS account_name,
    t.name AS client_team_name
FROM shipments s
LEFT JOIN accounts a ON a.id = s.account_id
LEFT JOIN client_teams t ON t.id = s.client_team_id
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M")


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _compose_display_name(country: str, clone_name: str, name: str = "") -> str:
    country = country.strip()
    clone_name = clone_name.strip()
    name = name.strip()
    secondary = clone_name or name
    if country and secondary:
        return f"{country}: {secondary}"
    return secondary or country


def validate_unit_quantity(value: float | int | None) -> float | None:
    if value is None:
        return None
    quantity = float(value)
    if quantity <= 0:
        raise ValueError("Unit quantity must be a positive number")
    if quantity > MAX_UNIT_QUANTITY:
        raise ValueError(f"Unit quantity must be at most {MAX_UNIT_QUANTITY:g}")
    return round(quantity, 3)


# Initial list matching the previous chat-based tracker
SEED_SHIPMENTS: tuple[dict[str, str | None], ...] = (
    {
        "country": "DE",
        "clone_name": "Oner",
        "status": "enroute",
        "expected_delivery_date": "2026-08-13",
    },
    {
        "country": "CA",
        "clone_name": "Durston",
        "status": "preparing",
        "expected_delivery_date": "2026-08-18",
    },
    {
        "country": "DE",
        "clone_name": "Oner",
        "status": "preparing",
        "expected_delivery_date": "2026-08-20",
    },
    {
        "country": "ATL",
        "clone_name": "Auto",
        "status": "preparing",
        "expected_delivery_date": "2026-08-19",
    },
    {
        "country": "LA",
        "clone_name": "Le Bon",
        "status": "standby",
        "expected_delivery_date": "2026-08-25",
    },
    {
        "country": "DE",
        "clone_name": "Blickle",
        "status": "standby",
        "expected_delivery_date": "2026-08-26",
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
                require_account=False,
            )
        await self.db.migrate_legacy_clone_to_accounts()
        await self.db.connection.commit()
        logger.info("Seeded %s initial shipments", len(SEED_SHIPMENTS))
        return len(SEED_SHIPMENTS)

    async def _require_account(self, account_id: int | None) -> None:
        if account_id is None:
            raise ValueError("Account is required")
        cursor = await self.db.connection.execute(
            "SELECT id FROM accounts WHERE id = ? AND archived = 0",
            (account_id,),
        )
        if await cursor.fetchone() is None:
            raise ValueError("Account not found")

    async def _require_team(self, client_team_id: int | None) -> None:
        if client_team_id is None:
            return
        cursor = await self.db.connection.execute(
            "SELECT id FROM client_teams WHERE id = ? AND archived = 0",
            (client_team_id,),
        )
        if await cursor.fetchone() is None:
            raise ValueError("Client team not found")

    async def create(
        self,
        *,
        country: str,
        clone_name: str = "",
        name: str | None = None,
        status: str = DEFAULT_STATUS,
        created_by: int | None = None,
        note: str | None = None,
        expected_delivery_date: str | None = None,
        account_id: int | None = None,
        client_team_id: int | None = None,
        unit_quantity: float | None = None,
        label_creation_date: str | None = None,
        scanned_in_date: str | None = None,
        require_account: bool = True,
    ) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"Invalid status: {status}")
        if status == DELIVERED_STATUS:
            raise ValueError("Create the shipment first, then mark it delivered")

        country = country.strip()
        clone_name = (clone_name or "").strip()
        shipment_name = (name or "").strip() or None
        if not country:
            raise ValueError("Country is required")
        if len(country) > MAX_COUNTRY_LEN:
            raise ValueError(f"Country is too long (max {MAX_COUNTRY_LEN})")
        if clone_name and len(clone_name) > MAX_CLONE_LEN:
            raise ValueError(f"Clone is too long (max {MAX_CLONE_LEN})")
        if shipment_name and len(shipment_name) > MAX_SHIPMENT_NAME_LEN:
            raise ValueError(f"Name is too long (max {MAX_SHIPMENT_NAME_LEN})")
        if note is not None and len(note) > MAX_NOTE_LEN:
            raise ValueError(f"Note is too long (max {MAX_NOTE_LEN})")

        if require_account:
            await self._require_account(account_id)
        elif account_id is not None:
            await self._require_account(account_id)
        await self._require_team(client_team_id)

        edd = coerce_iso_date(expected_delivery_date) if expected_delivery_date else None
        label_date = coerce_iso_date(label_creation_date) if label_creation_date else None
        scanned_date = coerce_iso_date(scanned_in_date) if scanned_in_date else None
        quantity = validate_unit_quantity(unit_quantity)

        display_name = _compose_display_name(country, clone_name, shipment_name or "")
        now = _now()
        try:
            cursor = await self.db.connection.execute(
                """
                INSERT INTO shipments (
                    country, clone_name, name, display_name, status, note,
                    expected_date, expected_delivery_date,
                    account_id, client_team_id, unit_quantity,
                    label_creation_date, scanned_in_date, delivered_date,
                    created_at, updated_at, created_by, archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 0)
                """,
                (
                    country,
                    clone_name or None,
                    shipment_name,
                    display_name,
                    status,
                    note,
                    edd,
                    edd,
                    account_id,
                    client_team_id,
                    quantity,
                    label_date,
                    scanned_date,
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
            SHIPMENT_SELECT + " WHERE s.id = ?",
            (shipment_id,),
        )
        return _row_to_dict(await cursor.fetchone())

    def _active_where(self) -> str:
        placeholders = ",".join("?" * len(ACTIVE_STATUSES))
        return f"s.archived = 0 AND s.status IN ({placeholders})"

    async def list_active(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" * len(ACTIVE_STATUSES))
        cursor = await self.db.connection.execute(
            f"""
            {SHIPMENT_SELECT}
            WHERE s.archived = 0 AND s.status IN ({placeholders})
            ORDER BY
                CASE
                    WHEN s.status = 'enroute' THEN 0
                    WHEN s.status = 'out_for_delivery' THEN 1
                    WHEN s.status = 'preparing' THEN 2
                    WHEN s.status = 'make_label' THEN 3
                    WHEN s.status = 'standby' THEN 4
                    ELSE 5
                END,
                s.id ASC
            """,
            ACTIVE_STATUSES,
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_by_status(self, status: str, *, archived: bool = False) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            f"""
            {SHIPMENT_SELECT}
            WHERE s.archived = ? AND s.status = ?
            ORDER BY s.updated_at DESC, s.id DESC
            """,
            (1 if archived else 0, status),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def count_by_status(self, *, archived: bool | None = False) -> dict[str, int]:
        sql = "SELECT status, COUNT(*) AS cnt FROM shipments"
        params: list[Any] = []
        if archived is not None:
            sql += " WHERE archived = ?"
            params.append(1 if archived else 0)
        sql += " GROUP BY status"
        cursor = await self.db.connection.execute(sql, params)
        counts = {status: 0 for status in STATUSES}
        for row in await cursor.fetchall():
            status = row["status"]
            if status in counts:
                counts[status] = row["cnt"]
        return counts

    async def dashboard_counts(self) -> dict[str, int]:
        active_ph = ",".join("?" * len(ACTIVE_STATUSES))
        transit_ph = ",".join("?" * len(IN_TRANSIT_STATUSES))
        working_ph = ",".join("?" * len(WORKING_STATUSES))
        cursor = await self.db.connection.execute(
            f"""
            SELECT
                SUM(CASE WHEN archived = 0 AND status IN ({active_ph}) THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN archived = 0 AND status IN ({transit_ph}) THEN 1 ELSE 0 END) AS in_transit,
                SUM(CASE WHEN archived = 0 AND status = ? THEN 1 ELSE 0 END) AS enroute,
                SUM(CASE WHEN archived = 0 AND status = ? THEN 1 ELSE 0 END) AS out_for_delivery,
                SUM(CASE WHEN archived = 0 AND status IN ({working_ph}) THEN 1 ELSE 0 END) AS working,
                SUM(CASE WHEN archived = 0 AND status = ? THEN 1 ELSE 0 END) AS delivered,
                SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END) AS archived
            FROM shipments
            """,
            (
                *ACTIVE_STATUSES,
                *IN_TRANSIT_STATUSES,
                "enroute",
                "out_for_delivery",
                *WORKING_STATUSES,
                DELIVERED_STATUS,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            return {
                "active": 0,
                "in_transit": 0,
                "enroute": 0,
                "out_for_delivery": 0,
                "working": 0,
                "delivered": 0,
                "archived": 0,
            }
        return {key: int(row[key] or 0) for key in row.keys()}

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Legacy active-only search used by the old Telegram UI."""
        items, _total = await self.list_filtered(
            query=query,
            archived=False,
            active_only=True,
            limit=50,
            offset=0,
        )
        return items

    async def list_filtered(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        account_id: int | None = None,
        unassigned_account: bool = False,
        client_team_id: int | None = None,
        archived: bool | None = False,
        active_only: bool = False,
        completed_only: bool = False,
        in_archive: bool = False,
        searchable: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = ["1=1"]
        params: list[Any] = []

        if in_archive:
            # Archive is the delivered/completed history plus manually hidden rows.
            # Do not require archived=1, account activity, or a current-shipment flag.
            where.append("(s.archived = 1 OR s.status = ?)")
            params.append(DELIVERED_STATUS)
        elif searchable:
            # Search keeps delivered rows visible even if they were also archived.
            where.append("(s.archived = 0 OR s.status = ?)")
            params.append(DELIVERED_STATUS)
        elif archived is not None:
            where.append("s.archived = ?")
            params.append(1 if archived else 0)
        if active_only:
            placeholders = ",".join("?" * len(ACTIVE_STATUSES))
            where.append(f"s.status IN ({placeholders})")
            params.extend(ACTIVE_STATUSES)
        if completed_only:
            where.append("s.status = ?")
            params.append(DELIVERED_STATUS)
        if status:
            if status not in STATUSES:
                raise ValueError(f"Invalid status: {status}")
            where.append("s.status = ?")
            params.append(status)
        if unassigned_account:
            where.append("s.account_id IS NULL")
        elif account_id is not None:
            where.append("s.account_id = ?")
            params.append(account_id)
        if client_team_id is not None:
            where.append("s.client_team_id = ?")
            params.append(client_team_id)

        q = (query or "").strip()
        if q:
            pattern = f"%{q}%"
            where.append(
                """
                (
                    s.country LIKE ? COLLATE NOCASE
                 OR s.clone_name LIKE ? COLLATE NOCASE
                 OR s.name LIKE ? COLLATE NOCASE
                 OR s.display_name LIKE ? COLLATE NOCASE
                 OR a.name LIKE ? COLLATE NOCASE
                 OR t.name LIKE ? COLLATE NOCASE
                 OR CAST(s.id AS TEXT) LIKE ?
                )
                """
            )
            params.extend([pattern, pattern, pattern, pattern, pattern, pattern, pattern])

        where_sql = " AND ".join(where)
        count_sql = f"""
            SELECT COUNT(*) AS cnt
            FROM shipments s
            LEFT JOIN accounts a ON a.id = s.account_id
            LEFT JOIN client_teams t ON t.id = s.client_team_id
            WHERE {where_sql}
        """
        cursor = await self.db.connection.execute(count_sql, params)
        row = await cursor.fetchone()
        total = int(row["cnt"]) if row else 0

        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        list_sql = f"""
            {SHIPMENT_SELECT}
            WHERE {where_sql}
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT ? OFFSET ?
        """
        cursor = await self.db.connection.execute(list_sql, [*params, limit, offset])
        items = [dict(row) for row in await cursor.fetchall()]
        return items, total

    async def distinct_countries(self) -> list[str]:
        return await self._distinct_ranked("country")

    async def distinct_clones(self) -> list[str]:
        return await self._distinct_ranked("clone_name")

    async def _distinct_ranked(self, column: str) -> list[str]:
        if column not in {"country", "clone_name"}:
            raise ValueError(f"Unsupported distinct column: {column}")
        cursor = await self.db.connection.execute(
            f"""
            SELECT {column} AS value, COUNT(*) AS cnt, MAX(id) AS last_id
            FROM shipments
            WHERE {column} IS NOT NULL AND TRIM({column}) != ''
            GROUP BY {column}
            ORDER BY cnt DESC, last_id DESC, value COLLATE NOCASE
            """
        )
        return [row["value"] for row in await cursor.fetchall()]

    async def list_history(self, shipment_id: int) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT * FROM status_history
            WHERE shipment_id = ?
            ORDER BY id ASC
            """,
            (shipment_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def _write_status_history(
        self,
        shipment_id: int,
        old_status: str | None,
        new_status: str,
        changed_by: int | None,
        changed_at: str,
    ) -> None:
        await self.db.connection.execute(
            """
            INSERT INTO status_history (
                shipment_id, old_status, new_status, changed_by, changed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (shipment_id, old_status, new_status, changed_by, changed_at),
        )

    async def update_status(
        self,
        shipment_id: int,
        new_status: str,
        *,
        changed_by: int | None = None,
        delivered_date: str | None = None,
        allow_archived: bool = False,
    ) -> dict[str, Any] | None:
        if new_status not in STATUSES:
            raise ValueError(f"Invalid status: {new_status}")

        shipment = await self.get_by_id(shipment_id)
        if shipment is None:
            return None
        if shipment["archived"] and not allow_archived:
            return None

        old_status = shipment["status"]
        now = _now()
        if old_status == new_status:
            return shipment

        delivered = shipment.get("delivered_date")
        if new_status == DELIVERED_STATUS:
            delivered = extract_date_component(delivered) or delivered_date
        # Leaving Delivered keeps delivered_date as historical data.

        try:
            await self.db.connection.execute(
                """
                UPDATE shipments
                SET status = ?, delivered_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, delivered, now, shipment_id),
            )
            await self._write_status_history(
                shipment_id, old_status, new_status, changed_by, now
            )
            if new_status == DELIVERED_STATUS:
                await self.cancel_active_reminders(shipment_id)
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

    async def complete(
        self,
        shipment_id: int,
        *,
        changed_by: int | None = None,
        delivered_date: str,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            return None
        if shipment["status"] == DELIVERED_STATUS and shipment.get("delivered_date"):
            return shipment
        if shipment["status"] == DELIVERED_STATUS:
            date_value = coerce_iso_date(delivered_date)
            if date_value is None:
                raise ValueError("delivered_date is required")
            now = _now()
            await self.db.connection.execute(
                """
                UPDATE shipments
                SET delivered_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (date_value, now, shipment_id),
            )
            await self.db.connection.commit()
            return await self.get_by_id(shipment_id)

        date_value = coerce_iso_date(delivered_date)
        if date_value is None:
            raise ValueError("delivered_date is required")
        return await self.update_status(
            shipment_id,
            DELIVERED_STATUS,
            changed_by=changed_by,
            delivered_date=date_value,
        )

    async def update_fields(
        self,
        shipment_id: int,
        *,
        country: str | None = None,
        clone_name: str | None = None,
        name: str | None | object = Ellipsis,
        note: str | None | object = Ellipsis,
        expected_delivery_date: str | None | object = Ellipsis,
        label_creation_date: str | None | object = Ellipsis,
        scanned_in_date: str | None | object = Ellipsis,
        account_id: int | None | object = Ellipsis,
        client_team_id: int | None | object = Ellipsis,
        unit_quantity: float | None | object = Ellipsis,
        allow_archived: bool = False,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None:
            return None
        if shipment["archived"] and not allow_archived:
            return None

        new_country = shipment.get("country") or ""
        new_clone = shipment.get("clone_name") or ""
        new_name = shipment.get("name") or ""
        if country is not None:
            new_country = country.strip()
            if not new_country:
                raise ValueError("Country is required")
            if len(new_country) > MAX_COUNTRY_LEN:
                raise ValueError(f"Country is too long (max {MAX_COUNTRY_LEN})")
        if clone_name is not None:
            new_clone = clone_name.strip()
            if not new_clone:
                raise ValueError("Clone is required")
            if len(new_clone) > MAX_CLONE_LEN:
                raise ValueError(f"Clone is too long (max {MAX_CLONE_LEN})")

        assignments: list[str] = []
        params: list[Any] = []

        if name is not Ellipsis:
            cleaned = None if name is None else str(name).strip()
            if cleaned == "":
                cleaned = None
            if cleaned and len(cleaned) > MAX_SHIPMENT_NAME_LEN:
                raise ValueError(f"Name is too long (max {MAX_SHIPMENT_NAME_LEN})")
            new_name = cleaned or ""
            assignments.append("name = ?")
            params.append(cleaned)

        if country is not None or clone_name is not None or name is not Ellipsis:
            display_name = _compose_display_name(new_country, new_clone, new_name)
            assignments.extend(["country = ?", "clone_name = ?", "display_name = ?"])
            params.extend([new_country, new_clone, display_name])

        if note is not Ellipsis:
            note_value = None if note is None else str(note)
            if note_value is not None and len(note_value) > MAX_NOTE_LEN:
                raise ValueError(f"Note is too long (max {MAX_NOTE_LEN})")
            assignments.append("note = ?")
            params.append(note_value)

        for field, value in (
            ("expected_delivery_date", expected_delivery_date),
            ("label_creation_date", label_creation_date),
            ("scanned_in_date", scanned_in_date),
        ):
            if value is Ellipsis:
                continue
            date_value = coerce_iso_date(value) if value else None
            assignments.append(f"{field} = ?")
            params.append(date_value)
            if field == "expected_delivery_date":
                assignments.append("expected_date = ?")
                params.append(date_value)
                old_edd = extract_date_component(
                    shipment.get("expected_delivery_date") or shipment.get("expected_date")
                )
                if date_value != old_edd:
                    assignments.append("edd_48h_sent_for = NULL")
                    assignments.append("edd_24h_sent_for = NULL")

        if account_id is not Ellipsis:
            if account_id is None:
                raise ValueError("Account is required")
            await self._require_account(int(account_id))
            assignments.append("account_id = ?")
            params.append(int(account_id))

        if client_team_id is not Ellipsis:
            team_value = None if client_team_id is None else int(client_team_id)
            await self._require_team(team_value)
            assignments.append("client_team_id = ?")
            params.append(team_value)

        if unit_quantity is not Ellipsis:
            assignments.append("unit_quantity = ?")
            params.append(
                validate_unit_quantity(unit_quantity) if unit_quantity is not None else None
            )

        if not assignments:
            return shipment

        now = _now()
        assignments.append("updated_at = ?")
        params.append(now)
        params.append(shipment_id)
        await self.db.connection.execute(
            f"UPDATE shipments SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        await self.db.connection.commit()
        return await self.get_by_id(shipment_id)

    async def update_country(self, shipment_id: int, country: str) -> dict[str, Any] | None:
        return await self.update_fields(shipment_id, country=country)

    async def update_clone_name(self, shipment_id: int, clone_name: str) -> dict[str, Any] | None:
        return await self.update_fields(shipment_id, clone_name=clone_name)

    async def update_edd(
        self,
        shipment_id: int,
        expected_delivery_date: str,
    ) -> dict[str, Any] | None:
        date_value = extract_date_component(expected_delivery_date) or coerce_iso_date(
            expected_delivery_date
        )
        return await self.update_fields(
            shipment_id, expected_delivery_date=date_value
        )

    async def update_note(self, shipment_id: int, note: str | None) -> dict[str, Any] | None:
        return await self.update_fields(shipment_id, note=note)

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

    async def restore(
        self,
        shipment_id: int,
        *,
        changed_by: int | None = None,
    ) -> dict[str, Any] | None:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None:
            return None
        if not shipment["archived"]:
            return shipment

        now = _now()
        await self.db.connection.execute(
            """
            UPDATE shipments
            SET archived = 0, updated_at = ?
            WHERE id = ?
            """,
            (now, shipment_id),
        )
        await self.db.connection.commit()
        logger.info("Shipment restored id=%s by=%s", shipment_id, changed_by)
        return await self.get_by_id(shipment_id)

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
        allow_past: bool = False,
    ) -> dict[str, Any]:
        shipment = await self.get_by_id(shipment_id)
        if shipment is None or shipment["archived"]:
            raise ValueError("Shipment not available")
        if shipment["status"] == DELIVERED_STATUS:
            raise ValueError("Cannot set a reminder on a delivered shipment")

        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=timezone.utc)
        else:
            remind_at = remind_at.astimezone(timezone.utc)
        if not allow_past and remind_at <= now_utc():
            raise ValueError("Reminder must be in the future")

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
                   s.country, s.clone_name, s.name, s.display_name, s.status,
                   s.expected_delivery_date, s.expected_date, s.archived,
                   a.name AS account_name
            FROM shipment_reminders r
            JOIN shipments s ON s.id = r.shipment_id
            LEFT JOIN accounts a ON a.id = s.account_id
            WHERE r.cancelled = 0
              AND r.sent_at IS NULL
              AND s.archived = 0
              AND s.status != 'delivered'
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

    async def due_edd_reminders(
        self,
        *,
        now: datetime | None = None,
        tz_name: str = "UTC",
        reminder_hour: int = 9,
    ) -> list[dict[str, Any]]:
        """Return 48h/24h Expected Delivery reminders that are due and unsent."""
        now_dt = now or now_utc()
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        local_now = now_dt.astimezone(tz)

        cursor = await self.db.connection.execute(
            """
            SELECT
                s.id,
                s.name,
                s.clone_name,
                s.display_name,
                s.country,
                s.status,
                s.archived,
                s.unit_quantity,
                s.expected_delivery_date,
                s.expected_date,
                s.edd_48h_sent_for,
                s.edd_24h_sent_for,
                s.created_by,
                a.name AS account_name,
                t.name AS client_team_name
            FROM shipments s
            LEFT JOIN accounts a ON a.id = s.account_id
            LEFT JOIN client_teams t ON t.id = s.client_team_id
            WHERE s.archived = 0
              AND s.status != 'delivered'
              AND (
                    (s.expected_delivery_date IS NOT NULL AND s.expected_delivery_date != '')
                 OR (s.expected_date IS NOT NULL AND s.expected_date != '')
              )
            ORDER BY s.id ASC
            """
        )
        due: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            item = dict(row)
            edd = extract_date_component(
                item.get("expected_delivery_date") or item.get("expected_date")
            )
            if not edd:
                continue
            try:
                edd_date = date.fromisoformat(edd)
            except ValueError:
                continue
            for hours, sent_for in (
                (48, item.get("edd_48h_sent_for")),
                (24, item.get("edd_24h_sent_for")),
            ):
                if sent_for == edd:
                    continue
                if _edd_reminder_is_due(local_now, edd_date, hours, reminder_hour):
                    due.append({**item, "edd": edd, "edd_hours": hours})
                    break
        return due

    async def mark_edd_reminder_sent(
        self,
        shipment_id: int,
        hours: int,
        edd: str,
    ) -> bool:
        """Claim an EDD reminder for this shipment+date. True if this call won."""
        column = _edd_sent_column(hours)
        cursor = await self.db.connection.execute(
            f"""
            UPDATE shipments
            SET {column} = ?
            WHERE id = ?
              AND archived = 0
              AND status != 'delivered'
              AND (
                    expected_delivery_date = ?
                 OR (
                        (expected_delivery_date IS NULL OR expected_delivery_date = '')
                    AND expected_date = ?
                 )
              )
              AND ({column} IS NULL OR {column} != ?)
            """,
            (edd, shipment_id, edd, edd, edd),
        )
        await self.db.connection.commit()
        return (cursor.rowcount or 0) > 0

    async def clear_edd_reminder_sent(self, shipment_id: int, hours: int) -> None:
        column = _edd_sent_column(hours)
        await self.db.connection.execute(
            f"UPDATE shipments SET {column} = NULL WHERE id = ?",
            (shipment_id,),
        )
        await self.db.connection.commit()


def _edd_sent_column(hours: int) -> str:
    if hours == 48:
        return "edd_48h_sent_for"
    if hours == 24:
        return "edd_24h_sent_for"
    raise ValueError(f"Unsupported EDD reminder hours: {hours}")


def _edd_reminder_is_due(
    local_now: datetime,
    edd_date: date,
    hours: int,
    reminder_hour: int,
) -> bool:
    """True when now is in the 48h or 24h window before EDD at the daily reminder hour."""
    if hours == 48:
        window_start = datetime.combine(
            edd_date - timedelta(days=2),
            time(hour=reminder_hour),
            tzinfo=local_now.tzinfo,
        )
        window_end = datetime.combine(
            edd_date - timedelta(days=1),
            time(hour=reminder_hour),
            tzinfo=local_now.tzinfo,
        )
    elif hours == 24:
        window_start = datetime.combine(
            edd_date - timedelta(days=1),
            time(hour=reminder_hour),
            tzinfo=local_now.tzinfo,
        )
        window_end = datetime.combine(edd_date, time.min, tzinfo=local_now.tzinfo)
    else:
        return False
    return window_start <= local_now < window_end
