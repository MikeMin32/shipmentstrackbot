from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message

from bot_ui.callbacks import DateCB, NavCB, PickCB, ShipCB
from bot_ui.draft import draft_missing, new_draft
from bot_ui.format import (
    compact_title,
    display_title,
    format_account_compact,
    format_home,
    format_home_date,
    format_human_date,
)
from domain.countries import CODE_INDEX, country_code_to_flag, format_country_code, search_countries
from bot_ui.grouping import group_home_shipments, page_active_shipments, sort_by_edd
from domain.status import HOME_STATUS_ORDER, STATUS_EMOJI, status_emoji
from bot_ui.parse import parse_weight_text
from bot_ui.calendar import WEEKDAYS
from bot_ui.keyboards import details_keyboard, draft_keyboard
from bot_ui.views import use_named_picker, view_calendar, view_details, view_draft, view_home, view_picker
from bot_ui.workspace import is_outdated_workspace
from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository
from database.sessions import BotSessionRepository
from domain.status import OPERATIONAL_STATUSES
from handlers.workspace import _apply_picker, apply_date_value
from middlewares.auth import AccessControlMiddleware


async def _repos(tmp_path):
    db = Database(tmp_path / "bot-ui.db")
    await db.connect()
    return db, ShipmentRepository(db), AccountRepository(db), ClientTeamRepository(db), BotSessionRepository(db)


@pytest.mark.asyncio
async def test_home_groups_and_edd_order(tmp_path) -> None:
    db, repo, accounts, _teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Acme")
        later = await repo.create(
            country="DE",
            clone_name="Late",
            status="enroute",
            account_id=acc["id"],
            expected_delivery_date="2026-09-20",
            require_account=True,
        )
        soon = await repo.create(
            country="IT",
            clone_name="Soon",
            status="out_for_delivery",
            account_id=acc["id"],
            expected_delivery_date="2026-09-08",
            require_account=True,
        )
        undated = await repo.create(
            country="CA",
            clone_name="None",
            status="enroute",
            account_id=acc["id"],
            require_account=True,
        )
        working = await repo.create(
            country="LA",
            clone_name="Prep",
            status="preparing",
            account_id=acc["id"],
            expected_delivery_date="2026-09-07",
            require_account=True,
        )
        await repo.create(
            country="ATL",
            clone_name="Done",
            status="preparing",
            account_id=acc["id"],
            require_account=True,
        )
        delivered = await repo.create(
            country="UK",
            clone_name="Fin",
            status="preparing",
            account_id=acc["id"],
            require_account=True,
        )
        await repo.complete(delivered["id"], delivered_date="2026-09-04")
        archived = await repo.create(
            country="FR",
            clone_name="Old",
            status="enroute",
            account_id=acc["id"],
            require_account=True,
        )
        await repo.archive(archived["id"])

        active = await repo.list_active()
        grouped = dict(group_home_shipments(active))
        assert [item["id"] for item in grouped["enroute"]] == [later["id"], undated["id"]]
        assert [item["id"] for item in grouped["out_for_delivery"]] == [soon["id"]]
        assert working["id"] == grouped["preparing"][0]["id"]
        assert "make_label" not in grouped
        assert "standby" not in grouped
        assert all(item["status"] != "delivered" for item in active)
        assert all(not item["archived"] for item in active)

        view = await view_home(repo, accounts, tz_name="UTC")
        assert "SHIPMENT TRACKER" not in view.text
        assert "active ·" not in view.text
        assert "in transit" not in view.text.lower()
        assert "working" not in view.text.lower()
        assert "IN TRANSIT" not in view.text
        assert "WORKING ON" not in view.text
        assert "✈️ <b>EN ROUTE</b>" in view.text
        assert "🚚 <b>OUT FOR DELIVERY</b>" in view.text
        assert "📦 <b>PREPARING</b>" in view.text
        assert "🏷️ <b>MAKE LABEL</b>" not in view.text
        assert "⏸️ <b>STANDBY</b>" not in view.text
        assert view.text.index("EN ROUTE") < view.text.index("OUT FOR DELIVERY") < view.text.index("PREPARING")
        assert "1." in view.text
        assert "Acme" in view.text
        assert "Mini App URL is not configured" not in view.text
        assert view.name == "home"
        texts = [btn.text for row in view.markup.inline_keyboard for btn in row]
        assert "1" in texts
        assert "➕ Add" in texts
        assert any(text.startswith("📦 All ·") for text in texts)
        assert "⋯ More" not in texts
        assert "Open Mini App" not in texts
        assert not any(getattr(btn, "web_app", None) for row in view.markup.inline_keyboard for btn in row)
        assert not any("Kal" in text or "Soon" in text or "Prep" in text or "Late" in text for text in texts)
    finally:
        await db.close()


def test_account_compact_summary_and_plus_more() -> None:
    rows = [
        {"id": 1, "name": "Acme", "total": 8, "active": 3},
        {"id": 2, "name": "Atlas", "total": 5, "active": 1},
        {"id": 3, "name": "Beta", "total": 2, "active": 2},
        {"id": None, "name": "No account", "total": 12, "active": 9, "unassigned": True},
        {"id": 4, "name": "Other", "total": 1, "active": 0},
    ]
    line = format_account_compact(rows, limit=3)
    assert line.startswith("No account 12")
    assert "Acme 8" in line
    assert "+2 more" in line


def test_display_title_name_first_then_flagged_country() -> None:
    assert (
        display_title({"name": "Laptop Batch 4", "country": "DE", "account_name": "Oner", "id": 12})
        == "Laptop Batch 4 · 🇩🇪 DE"
    )
    assert (
        compact_title({"name": None, "country": "DE", "account_name": "Oner", "clone_name": "Oner", "id": 1})
        == "Oner · 🇩🇪 DE"
    )
    assert display_title({"name": "Kal", "country": "ATL", "id": 2}) == "Kal · ATL"
    assert display_title({"name": None, "country": "LA", "account_name": "Le Bon", "id": 3}) == "Le Bon · LA"
    assert country_code_to_flag("de") == "🇩🇪"
    assert country_code_to_flag("ATL") is None
    assert format_country_code("LA") == "LA"
    germany = search_countries("German")
    assert any(label.endswith("Germany") for _index, label in germany)


def test_human_date_omits_same_year() -> None:
    assert format_human_date("2026-09-08", today=__import__("datetime").date(2026, 9, 4)) == "Sep 08"
    assert format_human_date("2025-09-08", today=__import__("datetime").date(2026, 9, 4)) == "Sep 08, 2025"


def test_draft_requires_name_country_account() -> None:
    draft = new_draft()
    assert draft_missing(draft) == ["name", "country", "account"]
    draft["name"] = "Laptop Batch 4"
    draft["country"] = "DE"
    assert draft_missing(draft) == ["account"]
    draft["account_id"] = 1
    assert draft_missing(draft) == []


def test_weight_validation() -> None:
    assert parse_weight_text("8.4 kg") == 8.4
    with pytest.raises(ValueError):
        parse_weight_text("nope")
    with pytest.raises(ValueError):
        parse_weight_text("-1")
    with pytest.raises(ValueError):
        parse_weight_text("0")


def test_outdated_workspace_detects_old_message() -> None:
    session = {"message_id": 10, "chat_id": 1}
    current = SimpleNamespace(message_id=10)
    old = SimpleNamespace(message_id=9)
    assert is_outdated_workspace(session, current) is False
    assert is_outdated_workspace(session, old) is True
    assert is_outdated_workspace(None, current) is False


@pytest.mark.asyncio
async def test_unauthorized_user_is_denied() -> None:
    middleware = AccessControlMiddleware(frozenset({111}))
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock()
    result = await middleware(AsyncMock(), message, {"event_from_user": SimpleNamespace(id=999)})
    assert result is None
    message.answer.assert_awaited_with("Access denied.")


@pytest.mark.asyncio
async def test_session_upsert_and_home_view(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        cursor = await db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_ui_sessions'"
        )
        assert await cursor.fetchone() is not None
        await sessions.upsert(
            telegram_user_id=111,
            chat_id=222,
            message_id=333,
            current_view="home",
        )
        row = await sessions.get(111)
        assert row is not None
        assert row["message_id"] == 333
        homes = await sessions.list_by_view("home")
        assert len(homes) == 1
        await sessions.set_view(111, "details")
        assert (await sessions.get(111))["current_view"] == "details"
        assert await sessions.list_by_view("home") == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_shipment_open_details_and_malformed_id(tmp_path) -> None:
    db, repo, accounts, _teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Ops")
        shipment = await repo.create(
            country="ATL",
            clone_name="Kal",
            status="out_for_delivery",
            account_id=acc["id"],
            require_account=True,
        )
        view = await view_details(repo, shipment["id"], tz_name="UTC")
        assert view is not None
        assert "#{}".format(shipment["id"]) in view.text
        assert "ATL" in view.text
        assert "Ops" in view.text
        assert "Kal" not in view.text
        assert "Clone" not in view.text
        texts = [btn.text for row in view.markup.inline_keyboard for btn in row]
        assert "✏️ Name" in texts
        assert "🏢 Account" in texts
        assert "🧬 Clone" not in texts
        assert await view_details(repo, 99999, tz_name="UTC") is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_create_draft_render(tmp_path) -> None:
    db, _repo, accounts, teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Account A")
        draft = new_draft()
        draft["name"] = "Laptop Batch 4"
        draft["country"] = "DE"
        draft["account_id"] = acc["id"]
        view = await view_draft(draft, accounts, teams, tz_name="UTC")
        assert "NEW SHIPMENT" in view.text
        assert "Laptop Batch 4" in view.text
        assert "Germany" in view.text
        assert "Account A" in view.text
        assert "Clone" not in view.text
        texts = [btn.text for row in view.markup.inline_keyboard for btn in row]
        assert texts[:4] == ["✏️ Name", "🌍 Country", "🏢 Account", "👥 Team"]
        assert "🧬 Clone" not in texts
        assert "Create shipment" in view.markup.inline_keyboard[-2][0].text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_picker_status_and_account_selection(tmp_path) -> None:
    db, repo, accounts, teams, _sessions = await _repos(tmp_path)
    try:
        acc_a = await accounts.create("Account A")
        acc_b = await accounts.create("Account B")
        shipment = await repo.create(
            country="DE",
            clone_name="Oner",
            status="preparing",
            account_id=acc_a["id"],
            require_account=True,
        )
        state = _FakeState()
        await state.update_data(draft=None)
        enroute_index = OPERATIONAL_STATUSES.index("enroute")
        error = await _apply_picker(
            PickCB(x="s", k="st", t="s", i=shipment["id"], n=enroute_index),
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
        )
        assert error is None
        updated = await repo.get_by_id(shipment["id"])
        assert updated["status"] == "enroute"

        error = await _apply_picker(
            PickCB(x="s", k="acc", t="s", i=shipment["id"], n=acc_b["id"]),
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
        )
        assert error is None
        updated = await repo.get_by_id(shipment["id"])
        assert updated["account_id"] == acc_b["id"]

        error = await _apply_picker(
            PickCB(x="s", k="st", t="s", i=shipment["id"], n=99),
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
        )
        assert error == "Unknown status."
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delivered_archive_restore_and_dates(tmp_path) -> None:
    db, repo, accounts, _teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Ops")
        shipment = await repo.create(
            country="DE",
            clone_name="Oner",
            status="enroute",
            account_id=acc["id"],
            require_account=True,
        )
        state = _FakeState()
        err = await apply_date_value(
            repo=repo,
            state=state,
            target="s",
            shipment_id=shipment["id"],
            field="ed",
            iso="2026-09-08",
        )
        assert err is None
        row = await repo.get_by_id(shipment["id"])
        assert row["expected_delivery_date"] == "2026-09-08"

        first = await repo.complete(shipment["id"], delivered_date="2026-09-04")
        assert first["status"] == "delivered"
        assert first["archived"] == 0
        again = await repo.complete(shipment["id"], delivered_date="2026-09-10")
        assert again["delivered_date"] == "2026-09-04"

        archived = await repo.archive(shipment["id"])
        assert archived["archived"] == 1
        assert archived["status"] == "delivered"
        restored = await repo.restore(shipment["id"])
        assert restored["archived"] == 0
        assert restored["status"] == "delivered"
    finally:
        await db.close()


def test_picker_pagination_uses_ids_not_names() -> None:
    packed = PickCB(x="s", k="acc", t="s", i=11, p=2, n=15).pack()
    assert "Account" not in packed
    assert len(packed.encode()) <= 64
    date_packed = DateCB(x="s", f="ed", t="s", i=11, y=2026, m=9, n=8).pack()
    assert len(date_packed.encode()) <= 64
    ship_packed = ShipCB(x="vw", i=11).pack()
    assert len(ship_packed.encode()) <= 64
    nav_packed = NavCB(x="al", p=3, f="er").pack()
    assert len(nav_packed.encode()) <= 64


@pytest.mark.asyncio
async def test_distinct_country_picker_indexes(tmp_path) -> None:
    db, repo, accounts, teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Ops")
        await repo.create(country="DE", clone_name="A", account_id=acc["id"], require_account=True)
        await repo.create(country="CA", clone_name="B", account_id=acc["id"], require_account=True)
        await repo.create(country="DE", clone_name="C", account_id=acc["id"], require_account=True)
        values = await repo.distinct_countries()
        assert values[0] == "DE"
        state = _FakeState({"draft": new_draft()})
        error = await _apply_picker(
            PickCB(x="s", k="co", t="d", i=0, n=CODE_INDEX["DE"]),
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
        )
        assert error is None
        assert (await state.get_data())["draft"]["country"] == "DE"
    finally:
        await db.close()


def test_home_pages_nine_items() -> None:
    shipments = [
        {"id": i, "status": "enroute" if i <= 12 else "preparing", "expected_delivery_date": None}
        for i in range(1, 39)
    ]
    page_items, page, pages, total = page_active_shipments(shipments, 0, size=9)
    assert len(page_items) == 9
    assert page == 0
    assert pages == 5
    assert total == 38
    assert all(item["status"] == "enroute" for item in page_items)
    page_two, page, pages, total = page_active_shipments(shipments, 1, size=9)
    assert page == 1
    assert [item["id"] for item in page_two] == list(range(10, 13)) + list(range(13, 19))


def test_home_orders_within_status_by_edd() -> None:
    shipments = [
        {"id": 3, "status": "enroute", "expected_delivery_date": None},
        {"id": 2, "status": "enroute", "expected_delivery_date": "2026-09-20"},
        {"id": 1, "status": "enroute", "expected_delivery_date": "2026-09-08"},
        {"id": 5, "status": "preparing", "expected_delivery_date": None},
        {"id": 4, "status": "preparing", "expected_delivery_date": "2026-09-07"},
        {"id": 6, "status": "out_for_delivery", "expected_delivery_date": "2026-09-09"},
    ]
    grouped = dict(group_home_shipments(shipments))
    assert [item["id"] for item in grouped["enroute"]] == [1, 2, 3]
    assert [item["id"] for item in grouped["out_for_delivery"]] == [6]
    assert [item["id"] for item in grouped["preparing"]] == [4, 5]
    page_items, _page, _pages, total = page_active_shipments(shipments, 0, size=9)
    assert total == 6
    assert [item["id"] for item in page_items] == [1, 2, 3, 6, 4, 5]


def test_sort_by_edd_stable_id() -> None:
    rows = [
        {"id": 2, "expected_delivery_date": "2026-09-08"},
        {"id": 1, "expected_delivery_date": "2026-09-08"},
        {"id": 3, "expected_delivery_date": None},
    ]
    ordered = sort_by_edd(rows)
    assert [row["id"] for row in ordered] == [1, 2, 3]


class _FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    async def get_data(self) -> dict:
        return dict(self._data)

    async def update_data(self, **kwargs) -> None:
        self._data.update(kwargs)


def test_home_format_uses_status_sections() -> None:
    today = __import__("datetime").date(2026, 9, 6)
    text = format_home(
        page_items=[
            {"id": 1, "country": "DE", "account_name": "Oner", "status": "enroute", "expected_delivery_date": "2026-09-07"},
            {"id": 2, "country": "IT", "account_name": "Fargo", "status": "out_for_delivery", "expected_delivery_date": "2026-09-06"},
            {"id": 3, "country": "LA", "account_name": "Bridge Publications", "status": "preparing", "expected_delivery_date": None},
            {"id": 4, "country": "CA", "account_name": "Durston", "status": "make_label", "expected_delivery_date": "2026-09-11"},
            {"id": 5, "country": "LA", "account_name": "Le Bon", "status": "standby", "expected_delivery_date": None},
            {"id": 6, "country": "ATL", "account_name": "Auto Direct", "status": "standby", "expected_delivery_date": None},
        ],
        account_line="Oner 2 · Auto Direct 1 · Blickle 1 · +2 more",
        today=today,
    )
    assert "SHIPMENT TRACKER" not in text
    assert "active ·" not in text
    assert "in transit" not in text.lower()
    assert "IN TRANSIT" not in text
    assert "WORKING ON" not in text
    assert text.startswith("✈️ <b>EN ROUTE</b>")
    assert "1. Oner · 🇩🇪 DE — Tomorrow, Sep 7" in text
    assert "2. Fargo · 🇮🇹 IT — Today, Sep 6" in text
    assert "3. Bridge Publications · LA" in text
    assert "Bridge Publications · LA —" not in text
    assert "4. Durston · 🇨🇦 CA — Fri, Sep 11" in text
    assert "5. Le Bon · LA" in text
    assert "6. Auto Direct · ATL" in text
    assert "🇩🇪" not in text.split("Le Bon")[1][:20]
    assert text.index("EN ROUTE") < text.index("OUT FOR DELIVERY") < text.index("PREPARING")
    assert text.index("PREPARING") < text.index("MAKE LABEL") < text.index("STANDBY")
    assert "\n\n🚚 <b>OUT FOR DELIVERY</b>\n" in text
    assert "\n\n📦 <b>PREPARING</b>\n" in text
    assert "\n\n🏷️ <b>MAKE LABEL</b>\n" in text
    assert "\n\n⏸️ <b>STANDBY</b>\n" in text
    assert "\n\n👤 <b>ACCOUNTS</b>\n" in text
    assert "Oner 2 · Auto Direct 1 · Blickle 1 · +2 more" in text
    assert text.count("\n\n") == 5


def test_home_omits_empty_status_sections() -> None:
    text = format_home(
        page_items=[
            {"id": 1, "country": "DE", "account_name": "Oner", "status": "enroute", "expected_delivery_date": "2026-09-08"},
            {"id": 2, "country": "LA", "account_name": "Le Bon", "status": "standby", "expected_delivery_date": None},
        ],
        account_line="Oner 1",
        today=__import__("datetime").date(2026, 9, 6),
    )
    assert "✈️ <b>EN ROUTE</b>" in text
    assert "⏸️ <b>STANDBY</b>" in text
    assert "OUT FOR DELIVERY" not in text
    assert "PREPARING" not in text
    assert "MAKE LABEL" not in text
    assert "No shipments" not in text
    assert "1. Oner · 🇩🇪 DE — Tue, Sep 8" in text
    assert "2. Le Bon · LA" in text


def test_home_date_formatting() -> None:
    today = __import__("datetime").date(2026, 9, 6)
    assert format_home_date("2026-09-06", today=today) == "Today, Sep 6"
    assert format_home_date("2026-09-07", today=today) == "Tomorrow, Sep 7"
    assert format_home_date("2026-09-07", today=today) != "Tomorrow"
    assert format_home_date("2026-09-08", today=today) == "Tue, Sep 8"
    assert format_home_date("2026-09-09", today=today) == "Wed, Sep 9"
    assert format_home_date("2026-09-11", today=today) == "Fri, Sep 11"
    assert format_home_date(None, today=today) is None
    assert "Monday" not in (format_home_date("2026-09-07", today=today) or "")
    assert "8" in (format_home_date("2026-09-08", today=today) or "")


def test_status_emoji_mapping() -> None:
    assert status_emoji("preparing") == "📦"
    assert status_emoji("make_label") == "🏷️"
    assert status_emoji("enroute") == "✈️"
    assert status_emoji("out_for_delivery") == "🚚"
    assert status_emoji("standby") == "⏸️"
    assert status_emoji("delivered") == "✅"
    assert HOME_STATUS_ORDER == (
        "enroute",
        "out_for_delivery",
        "preparing",
        "make_label",
        "standby",
    )
    assert set(STATUS_EMOJI) >= {
        "preparing",
        "make_label",
        "enroute",
        "out_for_delivery",
        "standby",
        "delivered",
    }


@pytest.mark.asyncio
async def test_home_paginates_same_workspace_message(tmp_path) -> None:
    db, repo, accounts, _teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Ops")
        for index in range(12):
            await repo.create(
                country="DE",
                clone_name=f"Item{index:02d}",
                status="enroute" if index < 5 else "preparing",
                account_id=acc["id"],
                require_account=True,
            )
        first = await view_home(repo, accounts, tz_name="UTC", page=0)
        assert "Showing 1–9 of 12" in first.text
        texts = [btn.text for row in first.markup.inline_keyboard for btn in row]
        assert texts[:9] == [str(i) for i in range(1, 10)]
        assert "1 / 2" in texts
        assert not any("Item" in text for text in texts)
        packed = first.markup.inline_keyboard[0][0].callback_data or ""
        assert "Item" not in packed
        second = await view_home(repo, accounts, tz_name="UTC", page=1)
        assert "Showing 10–12 of 12" in second.text
        assert "3." in second.text
        page_texts = [btn.text for row in second.markup.inline_keyboard for btn in row]
        assert page_texts[:3] == ["1", "2", "3"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_pickers_named_or_numbered() -> None:
    small = await view_picker(
        kind="co",
        target="d",
        shipment_id=0,
        page=0,
        query=None,
        current_id=None,
        current_label=None,
        items=[(CODE_INDEX["US"], "🇺🇸 United States"), (CODE_INDEX["DE"], "🇩🇪 Germany")],
        allow_new=False,
        allow_search=True,
        allow_clear=False,
        columns=2,
        section_label="Recently used:",
    )
    small_texts = [btn.text for row in small.markup.inline_keyboard for btn in row]
    assert "1. 🇺🇸 United States" in small.text
    assert "Recently used:" in small.text
    assert small_texts[:2] == ["1", "2"]
    assert "United States" not in small_texts
    assert "➕ New" not in small_texts

    large_items = [(i, f"Account {chr(65 + i)}") for i in range(10)]
    large = await view_picker(
        kind="acc",
        target="d",
        shipment_id=0,
        page=0,
        query=None,
        current_id=None,
        current_label=None,
        items=large_items,
        allow_new=True,
        allow_search=True,
        allow_clear=False,
        columns=1,
    )
    assert "1. Account A" in large.text
    assert "SELECT ACCOUNT" in large.text
    large_texts = [btn.text for row in large.markup.inline_keyboard for btn in row]
    assert large_texts[:2] == ["1", "2"]
    assert "Account A" not in large_texts
    packed = large.markup.inline_keyboard[0][0].callback_data or ""
    assert "Account" not in packed
    assert use_named_picker("st", [(0, "Preparing"), (1, "Make Label")]) is True

    status_items = [(i, name) for i, name in enumerate(["Preparing", "Make Label", "In Transit", "Out for Delivery", "Standby"])]
    status = await view_picker(
        kind="st",
        target="s",
        shipment_id=1,
        page=0,
        query=None,
        current_id=0,
        current_label="Preparing",
        items=status_items,
        allow_new=False,
        allow_search=False,
        allow_clear=False,
        columns=1,
    )
    status_texts = [btn.text for row in status.markup.inline_keyboard for btn in row]
    assert "Preparing" in status_texts or "✓ Preparing" in status_texts
    assert "1. Preparing" not in status.text


def _date_field_buttons(markup) -> dict[str, DateCB]:
    found: dict[str, DateCB] = {}
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.text not in {"🏷 Label", "📥 Scanned", "🚚 Expected"}:
                continue
            assert btn.callback_data
            found[btn.text] = DateCB.unpack(btn.callback_data)
    return found


def test_shipment_date_fields_open_calendar_directly() -> None:
    details = details_keyboard(
        {
            "id": 11,
            "archived": 0,
            "status": "enroute",
        }
    )
    draft = draft_keyboard()
    for markup in (details, draft):
        fields = _date_field_buttons(markup)
        assert set(fields) == {"🏷 Label", "📥 Scanned", "🚚 Expected"}
        assert {data.f for data in fields.values()} == {"lb", "sc", "ed"}
        assert all(data.x in {"m", "o"} for data in fields.values())

    view = view_calendar(
        field="sc",
        target="s",
        shipment_id=11,
        year=2026,
        month=9,
        current="2026-09-08",
        tz_name="UTC",
    )
    texts = [btn.text for row in view.markup.inline_keyboard for btn in row]
    assert texts[0] == "‹"
    assert "September 2026" in texts
    assert texts[2] == "›"
    assert texts[3:10] == list(WEEKDAYS)
    assert "[8]" in texts
    assert "Today" in texts
    assert "Clear" in texts
    assert "← Back" in texts
    assert "🗓 Calendar" not in texts
    assert "+2 days" not in texts
    assert "Yesterday" not in texts
    assert "Tomorrow" not in texts

    reminder = view_calendar(
        field="rm",
        target="s",
        shipment_id=11,
        year=2026,
        month=9,
        current=None,
        tz_name="UTC",
    )
    reminder_texts = [btn.text for row in reminder.markup.inline_keyboard for btn in row]
    assert "Today" in reminder_texts
    assert "Tomorrow" in reminder_texts


MINI_APP_PROMO = "Tap the button below to open the app."


BOT_UI_BANNED = (
    MINI_APP_PROMO,
    "Open Shipment Tracker",
    "Open Tracker",
    "Open Mini App",
    "WebAppInfo",
    "MenuButtonWebApp",
    'Command("app")',
    "⋯ More",
)


def test_mini_app_promo_is_not_auto_registered(tmp_path) -> None:
    from handlers import get_root_router
    from handlers.start import router as start_router
    from handlers.workspace import router as workspace_router
    from tests.conftest import make_config

    root = get_root_router(make_config(tmp_path))
    assert workspace_router in root.sub_routers
    assert start_router not in root.sub_routers
    assert not start_router.message.handlers
    commands = [
        getattr(handler.callback, "__name__", "")
        for observer in workspace_router.observers.values()
        for handler in observer.handlers
    ]
    assert "cmd_app" not in commands
    assert "cb_more" not in commands


def test_live_bot_sources_do_not_send_mini_app_promo() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    scanned = [
        root / "bot.py",
        root / "handlers",
        root / "bot_ui",
        root / "services",
        root / "keyboards",
    ]
    hits: list[str] = []
    for target in scanned:
        paths = [target] if target.is_file() else sorted(target.glob("**/*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for needle in BOT_UI_BANNED:
                if needle in text:
                    hits.append(f"{path.relative_to(root)}: {needle}")
    assert hits == []


@pytest.mark.asyncio
async def test_workspace_screens_remain_available(tmp_path) -> None:
    db, repo, accounts, teams, _sessions = await _repos(tmp_path)
    try:
        acc = await accounts.create("Ops")
        shipment = await repo.create(
            country="DE",
            name="Oner",
            clone_name="Oner",
            status="enroute",
            account_id=acc["id"],
            expected_delivery_date="2026-09-08",
            require_account=True,
        )
        home = await view_home(repo, accounts, tz_name="UTC")
        assert home.text.startswith("✈️ <b>EN ROUTE</b>")
        details = await view_details(repo, shipment["id"], tz_name="UTC")
        assert details is not None
        assert "✈️ En Route" in details.text
        draft = await view_draft(new_draft(), accounts, teams, tz_name="UTC")
        assert "NEW SHIPMENT" in draft.text
        calendar = view_calendar(
            field="ed",
            target="s",
            shipment_id=shipment["id"],
            year=2026,
            month=9,
            current="2026-09-08",
            tz_name="UTC",
        )
        assert "EXPECTED DELIVERY" in calendar.text
        status_items = [
            (index, f"{status_emoji(status)} {label}")
            for index, (status, label) in enumerate(
                [
                    ("preparing", "Preparing"),
                    ("make_label", "Make Label"),
                    ("enroute", "En Route"),
                    ("out_for_delivery", "Out For Delivery"),
                    ("standby", "Standby"),
                ]
            )
        ]
        status = await view_picker(
            kind="st",
            target="s",
            shipment_id=shipment["id"],
            page=0,
            query=None,
            current_id=2,
            current_label="✈️ En Route",
            items=status_items,
            allow_new=False,
            allow_search=False,
            allow_clear=False,
            columns=1,
        )
        texts = [btn.text for row in status.markup.inline_keyboard for btn in row]
        assert any("En Route" in text for text in texts)
        from bot_ui.views import view_accounts, view_archive, view_search_results

        search = await view_search_results(repo, "Oner", 0, tz_name="UTC")
        assert "SEARCH" in search.text
        archive = await view_archive(repo, 0, tz_name="UTC")
        assert "ARCHIVE" in archive.text
        acct = await view_accounts(accounts)
        assert "ACCOUNTS" in acct.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_start_menu_opens_workspace_home(tmp_path, monkeypatch) -> None:
    from handlers.workspace import cmd_menu
    from tests.conftest import make_config

    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    presented: list = []

    async def fake_present(*_args, view, **_kwargs):
        presented.append(view)
        return 1

    monkeypatch.setattr("handlers.workspace.present", fake_present)
    try:
        message = AsyncMock(spec=Message)
        message.from_user = SimpleNamespace(id=111)
        message.chat = SimpleNamespace(id=222)
        message.bot = AsyncMock()
        state = AsyncMock()
        state.clear = AsyncMock()
        await cmd_menu(
            message,
            state,
            repo,
            accounts,
            teams,
            sessions,
            make_config(tmp_path),
        )
        assert presented
        view = presented[0]
        assert MINI_APP_PROMO not in view.text
        assert "SHIPMENT TRACKER" not in view.text
        assert "Mini App" not in view.text
        assert "Open the app" not in view.text
        texts = [btn.text for row in view.markup.inline_keyboard for btn in row]
        assert "⋯ More" not in texts
        assert "Open Mini App" not in texts
        assert not any(getattr(btn, "web_app", None) for row in view.markup.inline_keyboard for btn in row)
    finally:
        await db.close()
