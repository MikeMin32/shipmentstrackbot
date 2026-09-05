from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from database.db import Database
from database.entities import AccountRepository
from database.repository import ShipmentRepository
from utils.dates import today_in_timezone


@pytest.mark.asyncio
async def test_delivered_date_uses_app_timezone(tmp_path: Path) -> None:
    tz_name = "Pacific/Kiritimati"
    db = Database(tmp_path / "tz.db")
    await db.connect()
    try:
        account = await AccountRepository(db).create("TZ")
        repo = ShipmentRepository(db)
        shipment = await repo.create(
            country="DE",
            clone_name="Oner",
            account_id=account["id"],
            require_account=True,
        )
        expected = datetime.now(ZoneInfo(tz_name)).date().isoformat()
        completed = await repo.complete(shipment["id"], delivered_date=today_in_timezone(tz_name).isoformat())
        assert completed is not None
        assert completed["delivered_date"] == expected
    finally:
        await db.close()
