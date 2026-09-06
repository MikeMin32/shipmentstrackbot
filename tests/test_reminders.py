from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
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


@pytest.mark.asyncio
async def test_edd_reminders_48h_and_24h_and_no_duplicates(tmp_path: Path) -> None:
    db = Database(tmp_path / "edd.db")
    await db.connect()
    try:
        account = await AccountRepository(db).create("Oner")
        team = await ClientTeamRepository(db).create("Stealth")
        repo = ShipmentRepository(db)
        shipment = await repo.create(
            country="DE",
            name="Oner Active",
            clone_name="Oner",
            status="enroute",
            created_by=111,
            account_id=account["id"],
            client_team_id=team["id"],
            unit_quantity=5,
            expected_delivery_date="2026-09-10",
            require_account=True,
        )

        before_48h = datetime(2026, 9, 8, 8, 59, tzinfo=timezone.utc)
        at_48h = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
        at_24h = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
        on_delivery_day = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)

        assert await repo.due_edd_reminders(now=before_48h, tz_name="UTC", reminder_hour=9) == []

        due_48 = await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9)
        assert len(due_48) == 1
        assert due_48[0]["id"] == shipment["id"]
        assert due_48[0]["edd_hours"] == 48
        assert due_48[0]["client_team_name"] == "Stealth"

        assert await repo.mark_edd_reminder_sent(shipment["id"], 48, "2026-09-10") is True
        assert await repo.mark_edd_reminder_sent(shipment["id"], 48, "2026-09-10") is False
        assert await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9) == []

        due_24 = await repo.due_edd_reminders(now=at_24h, tz_name="UTC", reminder_hour=9)
        assert len(due_24) == 1
        assert due_24[0]["edd_hours"] == 24
        assert await repo.mark_edd_reminder_sent(shipment["id"], 24, "2026-09-10") is True
        assert await repo.due_edd_reminders(now=at_24h, tz_name="UTC", reminder_hour=9) == []
        assert await repo.due_edd_reminders(now=on_delivery_day, tz_name="UTC", reminder_hour=9) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_edd_reminders_skip_archived_delivered_and_missing_date(tmp_path: Path) -> None:
    db = Database(tmp_path / "edd-skip.db")
    await db.connect()
    try:
        account = await AccountRepository(db).create("Ops")
        repo = ShipmentRepository(db)
        now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)

        await repo.create(
            country="DE",
            clone_name="NoDate",
            status="enroute",
            account_id=account["id"],
            require_account=True,
        )
        archived = await repo.create(
            country="IT",
            clone_name="Arch",
            status="enroute",
            account_id=account["id"],
            expected_delivery_date="2026-09-10",
            require_account=True,
        )
        await repo.archive(archived["id"])
        delivered = await repo.create(
            country="CA",
            clone_name="Done",
            status="preparing",
            account_id=account["id"],
            expected_delivery_date="2026-09-10",
            require_account=True,
        )
        await repo.complete(delivered["id"], delivered_date="2026-09-03")

        assert await repo.due_edd_reminders(now=now, tz_name="UTC", reminder_hour=9) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_edd_change_resets_reminders(tmp_path: Path) -> None:
    db = Database(tmp_path / "edd-change.db")
    await db.connect()
    try:
        account = await AccountRepository(db).create("Ops")
        repo = ShipmentRepository(db)
        shipment = await repo.create(
            country="DE",
            clone_name="Oner",
            status="enroute",
            account_id=account["id"],
            expected_delivery_date="2026-09-10",
            require_account=True,
        )
        at_48h = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
        due = await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9)
        assert due[0]["edd_hours"] == 48
        assert await repo.mark_edd_reminder_sent(shipment["id"], 48, "2026-09-10") is True
        assert await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9) == []

        updated = await repo.update_fields(
            shipment["id"],
            expected_delivery_date="2026-09-12",
        )
        assert updated is not None
        assert updated["edd_48h_sent_for"] is None
        assert updated["edd_24h_sent_for"] is None

        later_48h = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
        due_new = await repo.due_edd_reminders(now=later_48h, tz_name="UTC", reminder_hour=9)
        assert len(due_new) == 1
        assert due_new[0]["edd"] == "2026-09-12"
        assert due_new[0]["edd_hours"] == 48
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_edd_worker_claims_before_send_and_retries_on_failure(tmp_path: Path) -> None:
    db = Database(tmp_path / "edd-worker.db")
    await db.connect()
    try:
        account = await AccountRepository(db).create("Ops")
        repo = ShipmentRepository(db)
        shipment = await repo.create(
            country="DE",
            name="Oner Active",
            clone_name="Oner",
            status="enroute",
            created_by=111,
            account_id=account["id"],
            unit_quantity=5,
            expected_delivery_date="2026-09-10",
            require_account=True,
        )
        at_48h = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
        due = await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9)
        assert due

        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("network"))
        worker = ReminderWorker(
            bot=bot,
            repo=repo,
            recipient_ids=frozenset({111}),
            tz_name="UTC",
            reminder_hour=9,
        )
        await worker._deliver_edd(due[0])
        assert await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9)

        bot.send_message = AsyncMock()
        due_again = await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9)
        await worker._deliver_edd(due_again[0])
        assert bot.send_message.await_count == 1
        text = bot.send_message.await_args.kwargs["text"]
        assert "Oner Active (5u)" in text
        assert "in 48 hrs" in text
        assert await repo.due_edd_reminders(now=at_48h, tz_name="UTC", reminder_hour=9) == []

        reloaded = await repo.get_by_id(shipment["id"])
        assert reloaded is not None
        assert reloaded["edd_48h_sent_for"] == "2026-09-10"
    finally:
        await db.close()
