from __future__ import annotations

import pytest

from bot_ui.views import view_archive, view_details, view_home, view_search_results
from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository


async def _repos(tmp_path):
    db = Database(tmp_path / "archive-delivered.db")
    await db.connect()
    return db, ShipmentRepository(db), AccountRepository(db), ClientTeamRepository(db)


async def _create_open(repo, account_id: int, *, country: str, name: str, status: str = "preparing"):
    return await repo.create(
        account_id=account_id,
        country=country,
        name=name,
        clone_name=name,
        status=status,
        require_account=True,
    )


@pytest.mark.asyncio
async def test_delivered_shipment_appears_in_archive(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Archive Co")
        shipment = await _create_open(repo, account["id"], country="DE", name="Oner")
        await repo.complete(shipment["id"], delivered_date="2026-09-04")

        items, total = await repo.list_filtered(in_archive=True)
        assert total == 1
        assert items[0]["id"] == shipment["id"]
        assert items[0]["status"] == "delivered"
        assert items[0]["archived"] == 0

        view = await view_archive(repo, 0, tz_name="UTC")
        assert "ARCHIVE" in view.text
        assert "Oner" in view.text
        assert "✅" in view.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_existing_delivered_row_is_openable_from_archive(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Legacy Co")
        shipment = await _create_open(repo, account["id"], country="CA", name="Durston")
        await repo.update_status(shipment["id"], "enroute")
        await repo.complete(shipment["id"], delivered_date="2026-09-01")

        # Existing production shape: delivered, archived flag still 0.
        row = await repo.get_by_id(shipment["id"])
        assert row is not None
        assert row["status"] == "delivered"
        assert row["archived"] == 0

        archive = await view_archive(repo, 0, tz_name="UTC")
        assert "Durston" in archive.text
        texts = [btn.text for row in archive.markup.inline_keyboard for btn in row]
        assert "1" in texts

        details = await view_details(repo, shipment["id"], tz_name="UTC")
        assert details is not None
        assert "Durston" in details.text
        assert "Delivered" in details.text
        assert details.name == "details"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delivered_shipment_remains_searchable(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Search Co")
        shipment = await _create_open(repo, account["id"], country="IT", name="Fargo")
        await repo.complete(shipment["id"], delivered_date="2026-09-04")

        items, total = await repo.list_filtered(query="Fargo", searchable=True)
        assert total == 1
        assert items[0]["id"] == shipment["id"]

        by_id, _ = await repo.list_filtered(query=str(shipment["id"]), searchable=True)
        assert any(item["id"] == shipment["id"] for item in by_id)

        view = await view_search_results(repo, "Fargo", 0, tz_name="UTC")
        assert "Fargo" in view.text
        assert "SEARCH" in view.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delivered_shipment_leaves_active_dashboard(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Dash Co")
        open_row = await _create_open(
            repo, account["id"], country="DE", name="Active", status="enroute"
        )
        delivered = await _create_open(repo, account["id"], country="CA", name="Finished")
        await repo.complete(delivered["id"], delivered_date="2026-09-04")

        active = await repo.list_active()
        ids = {item["id"] for item in active}
        assert open_row["id"] in ids
        assert delivered["id"] not in ids
        assert all(item["status"] != "delivered" for item in active)

        home = await view_home(repo, accounts, tz_name="UTC")
        assert "Finished" not in home.text
        assert "Active" in home.text
        assert "ARCHIVE" not in home.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_active_account_returns_to_standby_when_no_open_shipments(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Idle Co")
        shipment = await _create_open(repo, account["id"], country="LA", name="Last One")
        await repo.complete(shipment["id"], delivered_date="2026-09-04")

        standby = await accounts.list_standby()
        assert [row["id"] for row in standby] == [account["id"]]

        home = await view_home(repo, accounts, tz_name="UTC")
        assert "⏸️ <b>STANDBY</b>" in home.text
        assert "Idle Co" in home.text
        assert "Last One" not in home.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_account_with_another_open_shipment_stays_off_standby(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Busy Co")
        first = await _create_open(repo, account["id"], country="DE", name="Done")
        await _create_open(repo, account["id"], country="CA", name="Still Open", status="enroute")
        await repo.complete(first["id"], delivered_date="2026-09-04")

        assert await accounts.list_standby() == []
        home = await view_home(repo, accounts, tz_name="UTC")
        assert "⏸️ <b>STANDBY</b>" not in home.text
        assert "Still Open" in home.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_inactive_account_does_not_appear_in_standby(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Retired Co")
        shipment = await _create_open(repo, account["id"], country="UK", name="Old Job")
        await repo.complete(shipment["id"], delivered_date="2026-09-04")
        await accounts.archive(account["id"])

        assert await accounts.list_standby() == []
        home = await view_home(repo, accounts, tz_name="UTC")
        assert "⏸️ <b>STANDBY</b>" not in home.text
        assert "Retired Co" not in home.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_archive_ignores_account_active_state(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        active = await accounts.create("Live Co")
        inactive = await accounts.create("Hidden Co")
        live = await _create_open(repo, active["id"], country="DE", name="Live Job")
        hidden = await _create_open(repo, inactive["id"], country="CA", name="Hidden Job")
        await repo.complete(live["id"], delivered_date="2026-09-04")
        await repo.complete(hidden["id"], delivered_date="2026-09-05")
        await accounts.archive(inactive["id"])

        items, total = await repo.list_filtered(in_archive=True)
        ids = {item["id"] for item in items}
        assert total == 2
        assert live["id"] in ids
        assert hidden["id"] in ids

        view = await view_archive(repo, 0, tz_name="UTC")
        assert "Live Job" in view.text
        assert "Hidden Job" in view.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delivered_history_remains_intact(tmp_path) -> None:
    db, repo, accounts, _teams = await _repos(tmp_path)
    try:
        account = await accounts.create("Hist Co")
        shipment = await _create_open(
            repo, account["id"], country="DE", name="Tracked", status="preparing"
        )
        await repo.update_status(shipment["id"], "make_label")
        await repo.update_status(shipment["id"], "enroute")
        before = await repo.list_history(shipment["id"])
        assert [event["new_status"] for event in before] == [
            "preparing",
            "make_label",
            "enroute",
        ]

        completed = await repo.complete(shipment["id"], delivered_date="2026-09-04")
        assert completed is not None
        assert completed["id"] == shipment["id"]

        after = await repo.list_history(shipment["id"])
        assert [event["new_status"] for event in after[:3]] == [
            "preparing",
            "make_label",
            "enroute",
        ]
        assert after[-1]["new_status"] == "delivered"
        assert after[-1]["old_status"] == "enroute"
        assert len(after) == len(before) + 1

        details = await view_details(repo, shipment["id"], tz_name="UTC")
        assert details is not None
        assert "Tracked" in details.text
        archive = await view_archive(repo, 0, tz_name="UTC")
        assert "Tracked" in archive.text
    finally:
        await db.close()
