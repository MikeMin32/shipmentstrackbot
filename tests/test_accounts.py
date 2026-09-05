from __future__ import annotations

import pytest

from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository


@pytest.mark.asyncio
async def test_account_create_and_summary_counts(tmp_path) -> None:
    db = Database(tmp_path / "accounts.db")
    await db.connect()
    try:
        accounts = AccountRepository(db)
        repo = ShipmentRepository(db)
        first = await accounts.create("Account A")
        second = await accounts.create("Account B")

        for _ in range(2):
            await repo.create(
                country="DE",
                clone_name="Oner",
                account_id=first["id"],
                require_account=True,
            )
        created = await repo.create(
            country="CA",
            clone_name="Durston",
            account_id=second["id"],
            require_account=True,
        )
        await repo.complete(created["id"], delivered_date="2026-09-03")
        await repo.archive(created["id"])

        summary = await accounts.summary()
        by_name = {row["name"]: row for row in summary}
        assert by_name["Account A"]["total"] == 2
        assert by_name["Account A"]["active"] == 2
        assert by_name["Account B"]["total"] == 1
        assert by_name["Account B"]["active"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_blank_account_name_rejected(tmp_path) -> None:
    db = Database(tmp_path / "blank-account.db")
    await db.connect()
    try:
        with pytest.raises(ValueError, match="Name is required"):
            await AccountRepository(db).create("   ")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_blank_team_name_rejected(tmp_path) -> None:
    db = Database(tmp_path / "blank-team.db")
    await db.connect()
    try:
        with pytest.raises(ValueError, match="Name is required"):
            await ClientTeamRepository(db).create("   ")
    finally:
        await db.close()
