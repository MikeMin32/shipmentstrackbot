"""Lightweight SQLite-backed reminder poller."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from database.repository import ShipmentRepository
from keyboards.inline import open_shipment_keyboard
from utils.formatting import format_reminder_notice

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30


class ReminderWorker:
    def __init__(self, bot: Bot, repo: ShipmentRepository) -> None:
        self.bot = bot
        self.repo = repo
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="reminder-worker")
        logger.info("Reminder worker started (interval=%ss)", POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Reminder worker stopped")

    async def _run(self) -> None:
        # Deliver any overdue reminders immediately on startup
        await self._tick()
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=POLL_INTERVAL_SECONDS,
                )
                break
            except asyncio.TimeoutError:
                await self._tick()

    async def _tick(self) -> None:
        try:
            due = await self.repo.due_reminders()
        except Exception:
            logger.exception("Failed to query due reminders")
            return

        for row in due:
            await self._deliver(row)

    async def _deliver(self, row: dict) -> None:
        reminder_id = row["id"]
        shipment_id = row["shipment_id"]
        user_id = row.get("created_by")
        if not user_id:
            logger.warning(
                "Reminder id=%s has no created_by; cancelling", reminder_id
            )
            await self.repo.cancel_active_reminders(shipment_id)
            await self.repo.db.connection.commit()
            return

        # Claim first to avoid duplicate sends across overlapping ticks
        claimed = await self.repo.mark_reminder_sent(reminder_id)
        if not claimed:
            return

        shipment = {
            "id": shipment_id,
            "country": row.get("country"),
            "clone_name": row.get("clone_name"),
            "display_name": row.get("display_name"),
            "status": row.get("status"),
            "expected_delivery_date": row.get("expected_delivery_date"),
            "expected_date": row.get("expected_date"),
        }
        text = format_reminder_notice(shipment)
        try:
            await self.bot.send_message(
                chat_id=int(user_id),
                text=text,
                reply_markup=open_shipment_keyboard(shipment_id),
            )
            logger.info(
                "Reminder delivered id=%s shipment_id=%s user=%s",
                reminder_id,
                shipment_id,
                user_id,
            )
        except TelegramAPIError:
            logger.exception(
                "Failed to deliver reminder id=%s; will retry later", reminder_id
            )
            await self.repo.db.connection.execute(
                """
                UPDATE shipment_reminders
                SET sent_at = NULL
                WHERE id = ? AND cancelled = 0
                """,
                (reminder_id,),
            )
            await self.repo.db.connection.commit()
        except Exception:
            logger.exception("Unexpected reminder delivery error id=%s", reminder_id)
            await self.repo.db.connection.execute(
                """
                UPDATE shipment_reminders
                SET sent_at = NULL
                WHERE id = ? AND cancelled = 0
                """,
                (reminder_id,),
            )
            await self.repo.db.connection.commit()
