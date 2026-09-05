from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository, validate_box_weight


async def _repos(tmp_path):
    db = Database(tmp_path / "shipments.db")
    await db.connect()
    return db, ShipmentRepository(db), AccountRepository(db), ClientTeamRepository(db)


@pytest.mark.asyncio
async def test_create_update_complete_archive_restore(tmp_path) -> None:
    db, repo, accounts, teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Account A")
        team = await teams.create("Team Alpha")
        shipment = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            name="Oner",
            client_team_id=team["id"],
            box_weight=8.4,
            status="preparing",
            label_creation_date="2026-09-01",
            scanned_in_date="2026-09-02",
            expected_delivery_date="2026-09-08",
            note="Handle with care",
            require_account=True,
        )
        assert shipment["account_name"] == "Account A"
        assert shipment["client_team_name"] == "Team Alpha"
        assert shipment["box_weight"] == 8.4
        assert shipment["status"] == "preparing"
        assert shipment["archived"] == 0
        assert shipment["delivered_date"] is None

        updated = await repo.update_fields(
            shipment["id"],
            country="CA",
            clone_name="Durston",
        )
        assert updated is not None
        assert updated["country"] == "CA"
        assert updated["clone_name"] == "Durston"

        status = await repo.update_status(shipment["id"], "enroute")
        assert status is not None
        assert status["status"] == "enroute"

        completed = await repo.complete(shipment["id"], delivered_date="2026-09-04")
        assert completed is not None
        assert completed["status"] == "delivered"
        assert completed["delivered_date"] == "2026-09-04"
        assert completed["archived"] == 0

        active, _ = await repo.list_filtered(active_only=True, archived=False)
        assert all(item["id"] != shipment["id"] for item in active)

        completed_list, _ = await repo.list_filtered(completed_only=True, archived=False)
        assert any(item["id"] == shipment["id"] for item in completed_list)

        archived = await repo.archive(shipment["id"])
        assert archived is not None
        assert archived["archived"] == 1
        assert archived["status"] == "delivered"

        archive_list, _ = await repo.list_filtered(archived=True)
        assert any(item["id"] == shipment["id"] for item in archive_list)

        restored = await repo.restore(shipment["id"])
        assert restored is not None
        assert restored["archived"] == 0
        assert restored["status"] == "delivered"

        again = await repo.complete(shipment["id"], delivered_date="2026-09-10")
        assert again is not None
        assert again["delivered_date"] == "2026-09-04"

        reverted = await repo.update_status(shipment["id"], "preparing")
        assert reverted is not None
        assert reverted["status"] == "preparing"
        assert reverted["delivered_date"] == "2026-09-04"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_active_archive_restore_keeps_status(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Ops")
        shipment = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            status="standby",
            require_account=True,
        )
        archived = await repo.archive(shipment["id"])
        assert archived is not None
        assert archived["archived"] == 1
        assert archived["status"] == "standby"
        restored = await repo.restore(shipment["id"])
        assert restored is not None
        assert restored["archived"] == 0
        assert restored["status"] == "standby"
        active = await repo.list_active()
        assert any(item["id"] == shipment["id"] for item in active)
    finally:
        await db.close()


def test_invalid_weight_rejected() -> None:
    with pytest.raises(ValueError):
        validate_box_weight(-2)


@pytest.mark.asyncio
async def test_new_shipment_requires_account(tmp_path) -> None:
    db, repo, _accounts, _teams = await _repos(tmp_path)
    try:
        with pytest.raises(ValueError, match="Account is required"):
            await repo.create(country="DE", clone_name="Oner")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reminder_rejects_past(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Remind")
        shipment = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            require_account=True,
        )
        with pytest.raises(ValueError, match="future"):
            await repo.set_reminder(
                shipment["id"],
                datetime(2000, 1, 1, tzinfo=timezone.utc),
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_history_recorded(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Hist")
        shipment = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            status="preparing",
            require_account=True,
        )
        await repo.update_status(shipment["id"], "make_label")
        history = await repo.list_history(shipment["id"])
        assert len(history) >= 2
        assert history[-1]["new_status"] == "make_label"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_history_no_duplicate_on_same_status(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Same")
        shipment = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            status="preparing",
            require_account=True,
        )
        before = await repo.list_history(shipment["id"])
        await repo.update_status(shipment["id"], "preparing")
        after = await repo.list_history(shipment["id"])
        assert len(after) == len(before)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_search_by_id_and_filters(tmp_path) -> None:
    db, repo, accounts, teams = await _repos(tmp_path)
    try:
        account = await accounts.create("SearchAcc")
        team = await teams.create("SearchTeam")
        first = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            client_team_id=team["id"],
            status="out_for_delivery",
            require_account=True,
        )
        second = await repo.create(
            account_id=account["id"],
            country="CA",
            clone_name="Durston",
            status="preparing",
            require_account=True,
        )
        by_id, _ = await repo.list_filtered(query=str(first["id"]), archived=False)
        assert any(item["id"] == first["id"] for item in by_id)
        by_team, _ = await repo.list_filtered(query="SearchTeam", archived=False)
        assert any(item["id"] == first["id"] for item in by_team)
        by_status, _ = await repo.list_filtered(status="out_for_delivery", archived=False)
        assert {item["id"] for item in by_status} == {first["id"]}
        paged, total = await repo.list_filtered(archived=False, limit=1, offset=0)
        assert total >= 2
        assert len(paged) == 1
        page_two, _ = await repo.list_filtered(archived=False, limit=1, offset=1)
        assert page_two[0]["id"] != paged[0]["id"]
        assert second["id"] in {paged[0]["id"], page_two[0]["id"]}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_active_list_excludes_archived_and_delivered(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Dash")
        ofd = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            status="out_for_delivery",
            require_account=True,
        )
        delivered = await repo.create(
            account_id=account["id"],
            country="CA",
            clone_name="Durston",
            status="preparing",
            require_account=True,
        )
        await repo.complete(delivered["id"], delivered_date="2026-09-03")
        archived = await repo.create(
            account_id=account["id"],
            country="LA",
            clone_name="Le Bon",
            status="enroute",
            require_account=True,
        )
        await repo.archive(archived["id"])

        active = await repo.list_active()
        ids = {item["id"] for item in active}
        assert ofd["id"] in ids
        assert delivered["id"] not in ids
        assert archived["id"] not in ids
        assert all(item["status"] != "delivered" for item in active)
        assert all(not item["archived"] for item in active)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_malformed_edd_rejected_on_create(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Dates")
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            await repo.create(
                account_id=account["id"],
                country="DE",
                clone_name="Oner",
                expected_delivery_date="tomorrow",
                require_account=True,
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reminder_replace_and_complete_cancels(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Remind2")
        shipment = await repo.create(
            account_id=account["id"],
            country="DE",
            clone_name="Oner",
            require_account=True,
        )
        first = datetime.now(timezone.utc) + timedelta(days=2)
        second = datetime.now(timezone.utc) + timedelta(days=3)
        created = await repo.set_reminder(shipment["id"], first)
        replaced = await repo.set_reminder(shipment["id"], second)
        assert replaced["id"] != created["id"]
        active = await repo.get_active_reminder(shipment["id"])
        assert active is not None
        assert active["id"] == replaced["id"]
        await repo.complete(shipment["id"], delivered_date="2026-09-04")
        after = await repo.get_active_reminder(shipment["id"])
        assert after is None
        with pytest.raises(ValueError, match="delivered"):
            await repo.set_reminder(shipment["id"], second)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_missing_shipment_is_none(tmp_path) -> None:
    db, repo, _accounts, _teams = await _repos(tmp_path)
    try:
        assert await repo.get_by_id(999999) is None
        assert await repo.list_history(999999) == []
    finally:
        await db.close()
