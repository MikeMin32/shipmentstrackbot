from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from database.db import Database
from database.entities import AccountRepository
from database.repository import ShipmentRepository
from services.reminder_worker import ReminderWorker


@pytest.mark.asyncio
async def test_due_reminders_skip_delivered_and_archived(tmp_path: Path) -> None:
    db = Database(tmp_path / "reminders.db")
    await db.connect()
    try:
        account = await AccountRepository(db).create("RemindAcc")
        repo = ShipmentRepository(db)
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        future = datetime.now(timezone.utc) + timedelta(days=1)

        active = await repo.create(
            country="DE",
            clone_name="Oner",
            status="preparing",
            created_by=111,
            account_id=account["id"],
        )
        delivered = await repo.create(
            country="CA",
            clone_name="Durston",
            status="preparing",
            created_by=111,
            account_id=account["id"],
        )
        archived = await repo.create(
            country="LA",
            clone_name="Le Bon",
            status="enroute",
            created_by=111,
            account_id=account["id"],
        )
        await repo.set_reminder(active["id"], past, created_by=222, allow_past=True)
        await repo.set_reminder(delivered["id"], past, created_by=222, allow_past=True)
        await repo.complete(
            delivered["id"],
            changed_by=111,
            delivered_date="2026-09-03",
        )
        await repo.set_reminder(archived["id"], past, created_by=222, allow_past=True)
        await repo.archive(archived["id"], changed_by=111)

        later = await repo.create(
            country="ATL",
            clone_name="Auto",
            status="standby",
            created_by=111,
            account_id=account["id"],
        )
        await repo.set_reminder(later["id"], future, created_by=222)

        due = await repo.due_reminders()
        ids = {row["shipment_id"] for row in due}
        assert active["id"] in ids
        assert delivered["id"] not in ids
        assert archived["id"] not in ids
        assert later["id"] not in ids
        assert due[0]["created_by"] == 222

        reminder_id = due[0]["id"]
        assert await repo.mark_reminder_sent(reminder_id) is True
        assert await repo.mark_reminder_sent(reminder_id) is False

        worker = ReminderWorker(bot=None, repo=repo)
        assert worker._task is None
    finally:
        await db.close()
