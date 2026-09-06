"""Persistent Telegram workspace session (one active UI message per user)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.db import Database


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BotSessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, telegram_user_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            "SELECT * FROM bot_ui_sessions WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def upsert(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        message_id: int,
        current_view: str,
        needs_reposition: int = 0,
    ) -> dict[str, Any]:
        now = _now()
        await self.db.connection.execute(
            """
            INSERT INTO bot_ui_sessions (
                telegram_user_id, chat_id, message_id, current_view,
                updated_at, needs_reposition
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                current_view = excluded.current_view,
                updated_at = excluded.updated_at,
                needs_reposition = excluded.needs_reposition
            """,
            (
                telegram_user_id,
                chat_id,
                message_id,
                current_view,
                now,
                int(needs_reposition),
            ),
        )
        await self.db.connection.commit()
        session = await self.get(telegram_user_id)
        assert session is not None
        return session

    async def mark_needs_reposition(self, telegram_user_id: int) -> None:
        """Flag that notices were sent after the active workspace message."""
        await self.db.connection.execute(
            """
            UPDATE bot_ui_sessions
            SET needs_reposition = 1, updated_at = ?
            WHERE telegram_user_id = ?
            """,
            (_now(), telegram_user_id),
        )
        await self.db.connection.commit()

    async def set_view(self, telegram_user_id: int, current_view: str) -> None:
        await self.db.connection.execute(
            """
            UPDATE bot_ui_sessions
            SET current_view = ?, updated_at = ?
            WHERE telegram_user_id = ?
            """,
            (current_view, _now(), telegram_user_id),
        )
        await self.db.connection.commit()

    async def list_by_view(self, current_view: str) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            "SELECT * FROM bot_ui_sessions WHERE current_view = ?",
            (current_view,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_all(self) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute("SELECT * FROM bot_ui_sessions")
        return [dict(row) for row in await cursor.fetchall()]
