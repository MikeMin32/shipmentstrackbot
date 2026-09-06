"""Lightweight SQLite-backed reminder poller."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot_ui.format import format_edd_reminder_notice, format_reminder_notice
from bot_ui.keyboards import open_shipment_keyboard
from database.repository import ShipmentRepository

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30


class ReminderWorker:
    def __init__(
        self,
        bot: Bot,
        repo: ShipmentRepository,
        *,
        recipient_ids: frozenset[int] | None = None,
        tz_name: str = "UTC",
        reminder_hour: int = 9,
    ) -> None:
        self.bot = bot
        self.repo = repo
        self.recipient_ids = recipient_ids or frozenset()
        self.tz_name = tz_name
        self.reminder_hour = reminder_hour
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
            due = []

        for row in due:
            await self._deliver(row)

        try:
            edd_due = await self.repo.due_edd_reminders(
                tz_name=self.tz_name,
                reminder_hour=self.reminder_hour,
            )
        except Exception:
            logger.exception("Failed to query due Expected Delivery reminders")
            return

        for row in edd_due:
            await self._deliver_edd(row)

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

        claimed = await self.repo.mark_reminder_sent(reminder_id)
        if not claimed:
            return

        shipment = {
            "id": shipment_id,
            "country": row.get("country"),
            "clone_name": row.get("clone_name"),
            "name": row.get("name"),
            "account_name": row.get("account_name"),
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

    async def _deliver_edd(self, row: dict) -> None:
        shipment_id = int(row["id"])
        hours = int(row["edd_hours"])
        edd = row["edd"]
        recipients = set(self.recipient_ids)
        created_by = row.get("created_by")
        if created_by:
            recipients.add(int(created_by))
        if not recipients:
            logger.warning(
                "EDD reminder shipment_id=%s has no recipients; skipping",
                shipment_id,
            )
            return

        claimed = await self.repo.mark_edd_reminder_sent(shipment_id, hours, edd)
        if not claimed:
            return

        text = format_edd_reminder_notice(row, hours=hours)
        delivered = 0
        for user_id in sorted(recipients):
            try:
                await self.bot.send_message(
                    chat_id=int(user_id),
                    text=text,
                    reply_markup=open_shipment_keyboard(shipment_id),
                )
                delivered += 1
            except TelegramAPIError:
                logger.exception(
                    "Failed to deliver EDD %sh reminder shipment_id=%s user=%s",
                    hours,
                    shipment_id,
                    user_id,
                )
            except Exception:
                logger.exception(
                    "Unexpected EDD reminder delivery error shipment_id=%s user=%s",
                    shipment_id,
                    user_id,
                )

        if delivered == 0:
            await self.repo.clear_edd_reminder_sent(shipment_id, hours)
            logger.warning(
                "EDD %sh reminder shipment_id=%s not delivered; will retry later",
                hours,
                shipment_id,
            )
            return

        logger.info(
            "EDD %sh reminder delivered shipment_id=%s recipients=%s",
            hours,
            shipment_id,
            delivered,
        )
