"""Telegram shipment management bot entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import load_config
from database.db import Database
from database.repository import ShipmentRepository
from handlers import get_root_router
from middlewares.auth import AccessControlMiddleware
from services.reminder_worker import ReminderWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    db = Database(config.database_path)
    await db.connect()
    repo = ShipmentRepository(db)
    migrated = await repo.migrate_legacy_statuses()
    if migrated:
        logger.info("Migrated %s legacy status value(s) to standby", migrated)
    seeded = await repo.seed_if_empty()
    if seeded:
        logger.info("Database was empty — inserted %s shipments from seed list", seeded)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["repo"] = repo

    auth = AccessControlMiddleware(config.allowed_user_ids)
    dp.message.middleware(auth)
    dp.callback_query.middleware(auth)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("Unhandled update error: %s", event.exception)
        return True

    dp.include_router(get_root_router())

    worker = ReminderWorker(bot, repo)
    worker.start()

    logger.info("Starting shipment bot (long polling), times in UTC")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Shutting down")
        await worker.stop()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
    except Exception:
        logger.exception("Fatal error")
        raise
