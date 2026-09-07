"""Account and client-team persistence."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from database.db import Database

logger = logging.getLogger(__name__)

MAX_NAME_LEN = 120


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M")


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class NamedEntityRepository:
    """Shared CRUD for accounts and client_teams."""

    def __init__(self, db: Database, table: str) -> None:
        if table not in {"accounts", "client_teams"}:
            raise ValueError(f"Unsupported table: {table}")
        self.db = db
        self.table = table

    async def list_all(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {self.table}"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY name COLLATE NOCASE ASC, id ASC"
        cursor = await self.db.connection.execute(sql)
        return [dict(row) for row in await cursor.fetchall()]

    async def get_by_id(self, entity_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            f"SELECT * FROM {self.table} WHERE id = ?",
            (entity_id,),
        )
        return _row_to_dict(await cursor.fetchone())

    async def find_by_name(self, name: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        sql = f"SELECT * FROM {self.table} WHERE name = ? COLLATE NOCASE"
        if not include_archived:
            sql += " AND archived = 0"
        sql += " LIMIT 1"
        cursor = await self.db.connection.execute(sql, (name.strip(),))
        return _row_to_dict(await cursor.fetchone())

    async def create(self, name: str) -> dict[str, Any]:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Name is required")
        if len(cleaned) > MAX_NAME_LEN:
            raise ValueError(f"Name is too long (max {MAX_NAME_LEN})")

        existing = await self.find_by_name(cleaned, include_archived=True)
        if existing is not None:
            if existing["archived"]:
                now = _now()
                await self.db.connection.execute(
                    f"UPDATE {self.table} SET archived = 0, updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
                await self.db.connection.commit()
                restored = await self.get_by_id(existing["id"])
                assert restored is not None
                return restored
            raise ValueError("An item with this name already exists")

        now = _now()
        cursor = await self.db.connection.execute(
            f"""
            INSERT INTO {self.table} (name, created_at, updated_at, archived)
            VALUES (?, ?, ?, 0)
            """,
            (cleaned, now, now),
        )
        await self.db.connection.commit()
        entity = await self.get_by_id(cursor.lastrowid)
        assert entity is not None
        logger.info("Created %s id=%s name=%r", self.table, entity["id"], cleaned)
        return entity

    async def rename(self, entity_id: int, name: str) -> dict[str, Any] | None:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Name is required")
        if len(cleaned) > MAX_NAME_LEN:
            raise ValueError(f"Name is too long (max {MAX_NAME_LEN})")

        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None

        clash = await self.find_by_name(cleaned, include_archived=True)
        if clash is not None and clash["id"] != entity_id:
            raise ValueError("An item with this name already exists")

        now = _now()
        await self.db.connection.execute(
            f"UPDATE {self.table} SET name = ?, updated_at = ? WHERE id = ?",
            (cleaned, now, entity_id),
        )
        await self.db.connection.commit()
        return await self.get_by_id(entity_id)

    async def archive(self, entity_id: int) -> dict[str, Any] | None:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None
        now = _now()
        await self.db.connection.execute(
            f"UPDATE {self.table} SET archived = 1, updated_at = ? WHERE id = ?",
            (now, entity_id),
        )
        await self.db.connection.commit()
        return await self.get_by_id(entity_id)


class AccountRepository(NamedEntityRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db, "accounts")

    async def summary(self) -> list[dict[str, Any]]:
        """Total shipments per account, including completed/archived rows."""
        cursor = await self.db.connection.execute(
            """
            SELECT
                a.id,
                a.name,
                a.archived,
                COUNT(s.id) AS total,
                SUM(
                    CASE
                        WHEN s.id IS NOT NULL
                         AND s.archived = 0
                         AND s.status != 'delivered'
                        THEN 1 ELSE 0
                    END
                ) AS active
            FROM accounts a
            LEFT JOIN shipments s ON s.account_id = a.id
            WHERE a.archived = 0
            GROUP BY a.id, a.name, a.archived
            ORDER BY total DESC, a.name COLLATE NOCASE ASC
            """
        )
        rows = [dict(row) for row in await cursor.fetchall()]

        unassigned = await self.db.connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN archived = 0 AND status != 'delivered' THEN 1 ELSE 0
                    END
                ) AS active
            FROM shipments
            WHERE account_id IS NULL
            """
        )
        ua = await unassigned.fetchone()
        total = int(ua["total"]) if ua else 0
        if total:
            rows.append(
                {
                    "id": None,
                    "name": "No account",
                    "archived": 0,
                    "total": total,
                    "active": int(ua["active"] or 0) if ua else 0,
                    "unassigned": True,
                }
            )
        return rows

    async def list_standby(self) -> list[dict[str, Any]]:
        """Active accounts with no open shipments, ready to sit in Home STANDBY.

        Open = non-archived and not delivered. Inactive (archived) accounts are
        excluded. Accounts that have never had a shipment are excluded so Home
        only returns an account to Standby after its work is finished.
        """
        cursor = await self.db.connection.execute(
            """
            SELECT
                a.id,
                a.name,
                a.created_at,
                a.updated_at,
                a.archived,
                (
                    SELECT s.country
                    FROM shipments s
                    WHERE s.account_id = a.id
                      AND s.country IS NOT NULL
                      AND TRIM(s.country) != ''
                    ORDER BY s.updated_at DESC, s.id DESC
                    LIMIT 1
                ) AS country
            FROM accounts a
            WHERE a.archived = 0
              AND EXISTS (
                    SELECT 1 FROM shipments s WHERE s.account_id = a.id
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM shipments s
                    WHERE s.account_id = a.id
                      AND s.archived = 0
                      AND s.status != 'delivered'
              )
            ORDER BY a.name COLLATE NOCASE ASC, a.id ASC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]


class ClientTeamRepository(NamedEntityRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db, "client_teams")
