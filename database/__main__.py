"""Run database migrations: python -m database"""

from __future__ import annotations

import asyncio
import logging
import sys

from config import load_config
from database.db import Database
from database.repository import ShipmentRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)


async def migrate() -> None:
    config = load_config()
    db = Database(config.database_path)
    await db.connect()
    try:
        repo = ShipmentRepository(db)
        migrated = await repo.migrate_legacy_statuses()
        if migrated:
            print(f"Migrated {migrated} legacy status value(s) to standby")
        print(f"Database ready at {config.database_path}")
    finally:
        await db.close()


def main() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
