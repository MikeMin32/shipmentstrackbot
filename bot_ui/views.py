"""Render workspace screens from repository data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_ui import format as fmt
from bot_ui.callbacks import NavCB, PickCB, ShipCB
from bot_ui.draft import draft_missing
from bot_ui.grouping import page_active_shipments, sort_by_edd
from bot_ui.keyboards import (
    ACCOUNTS_PAGE_SIZE,
    HOME_PAGE_SIZE,
    NAMED_PICKER_MAX,
    PAGE_SIZE,
    PICKER_PAGE_LONG,
    PICKER_PAGE_SHORT,
    all_filter_rows,
    accounts_keyboard,
    calendar_keyboard,
    confirm_keyboard,
    details_keyboard,
    draft_keyboard,
    home_keyboard,
    input_back_keyboard,
    input_cancel_keyboard,
    picker_keyboard,
    reminder_keyboard,
    reminder_time_keyboard,
    shipment_list_keyboard,
    unit_quantity_input_keyboard,
)
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository
from domain.countries import (
    CODE_INDEX,
    country_picker_items,
    format_country_label,
    recent_country_items,
    search_countries,
)
from domain.status import (
    OPERATIONAL_STATUSES,
    STATUS_DISPLAY_LABELS,
    STATUS_SHORT,
    status_display_label,
    status_emoji,
    status_line,
)
from utils.dates import extract_date_component, today_in_timezone


@dataclass(frozen=True)
class View:
    text: str
    markup: InlineKeyboardMarkup
    name: str


PICKER_TITLES = {
    "acc": "🏢 SELECT ACCOUNT",
    "tm": "👥 SELECT TEAM",
    "st": "📦 SELECT STATUS",
    "co": "🌍 SELECT COUNTRY",
}

DATE_TITLES = {
    "lb": "📅 LABEL CREATION",
    "sc": "📅 SCANNED IN",
    "ed": "📅 EXPECTED DELIVERY",
    "rm": "⏰ REMINDER",
}


def app_today(tz_name: str) -> date:
    return today_in_timezone(tz_name)


def _pages(total: int, size: int = PAGE_SIZE) -> int:
    if total <= 0:
        return 1
    return max(1, (total + size - 1) // size)


def _page_items(items: list, page: int, size: int = PAGE_SIZE) -> tuple[list, int, int]:
    pages = _pages(len(items), size)
    page = max(0, min(page, pages - 1))
    start = page * size
    return items[start : start + size], page, pages


async def _paged_filtered(
    repo: ShipmentRepository,
    page: int,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], int, int, int]:
    items, total = await repo.list_filtered(
        **kwargs,
        limit=PAGE_SIZE,
        offset=max(0, page) * PAGE_SIZE,
    )
    pages = _pages(total)
    clamped = max(0, min(page, pages - 1))
    if clamped != page:
        items, total = await repo.list_filtered(
            **kwargs,
            limit=PAGE_SIZE,
            offset=clamped * PAGE_SIZE,
        )
    return items, total, clamped, pages


async def view_home(
    repo: ShipmentRepository,
    accounts: AccountRepository,
    *,
    tz_name: str,
    page: int = 0,
) -> View:
    today = app_today(tz_name)
    shipments = await repo.list_active()
    page_items, page, pages, total = page_active_shipments(
        shipments, page, size=HOME_PAGE_SIZE
    )
    summary = await accounts.summary()
    text = fmt.format_home(
        page_items=page_items,
        account_line=fmt.format_account_compact(summary),
        today=today,
        page=page,
        pages=pages,
        total_active=total,
        page_size=HOME_PAGE_SIZE,
    )
    return View(
        text,
        home_keyboard(
            page_items,
            total_active=total,
            page=page,
            pages=pages,
        ),
        "home",
    )


async def view_details(
    repo: ShipmentRepository,
    shipment_id: int,
    *,
    tz_name: str,
) -> View | None:
    shipment = await repo.get_by_id(shipment_id)
    if shipment is None:
        return None
    today = app_today(tz_name)
    reminder = await repo.get_active_reminder(shipment_id)
    reminder_text = None
    if reminder:
        reminder_text = fmt.format_reminder_at(reminder.get("remind_at"), tz_name=tz_name)
    return View(
        fmt.format_details(shipment, reminder_text=reminder_text, today=today),
        details_keyboard(shipment),
        "details",
    )


async def view_draft(
    draft: dict[str, Any],
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    *,
    tz_name: str,
) -> View:
    today = app_today(tz_name)
    account_name = None
    team_name = None
    if draft.get("account_id"):
        account = await accounts.get_by_id(int(draft["account_id"]))
        account_name = account["name"] if account else None
    if draft.get("client_team_id"):
        team = await teams.get_by_id(int(draft["client_team_id"]))
        team_name = team["name"] if team else None
    return View(
        fmt.format_draft(draft, account_name=account_name, team_name=team_name, today=today),
        draft_keyboard(),
        "draft",
    )


async def view_picker(
    *,
    kind: str,
    target: str,
    shipment_id: int,
    page: int,
    query: str | None,
    current_id: int | None,
    current_label: str | None,
    items: list[tuple[int, str]],
    allow_new: bool,
    allow_search: bool,
    allow_clear: bool,
    columns: int,
    section_label: str | None = None,
    extra_nav: list[InlineKeyboardButton] | None = None,
) -> View:
    filtered = items
    if query and kind != "co":
        needle = query.casefold()
        filtered = [(item_id, label) for item_id, label in items if needle in label.casefold()]
    named = use_named_picker(kind, filtered)
    size = picker_page_size(kind, filtered)
    page_items, page, pages = _page_items(filtered, page, size)
    title = PICKER_TITLES.get(kind, "SELECT")
    numbered_lines = None
    if not named:
        numbered_lines = [f"{index}. {fmt.esc(label)}" for index, (_item_id, label) in enumerate(page_items, start=1)]
        if pages > 1:
            start = page * size + 1
            end = page * size + len(page_items)
            numbered_lines.append(f"Showing {start}–{end} of {len(filtered)}")
    text = fmt.format_picker(
        title=title,
        current=current_label,
        numbered_items=numbered_lines,
        section_label=section_label,
    )
    if query:
        text += f"\nFilter: {fmt.esc(query)}"
    show_search = allow_search and (kind == "co" or not named or len(items) > NAMED_PICKER_MAX)
    return View(
        text,
        picker_keyboard(
            kind=kind,
            target=target,
            shipment_id=shipment_id,
            items=page_items,
            page=page,
            pages=pages,
            current_id=current_id,
            allow_new=allow_new,
            allow_search=show_search,
            allow_clear=allow_clear,
            columns=columns,
            numeric=not named,
            extra_nav=extra_nav,
        ),
        "picker",
    )


async def picker_items_for(
    kind: str,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
) -> list[tuple[int, str]]:
    if kind == "acc":
        rows = await accounts.list_all()
        return [(int(row["id"]), str(row["name"])) for row in rows]
    if kind == "tm":
        rows = await teams.list_all()
        return [(int(row["id"]), str(row["name"])) for row in rows]
    if kind == "st":
        return [
            (index, status_line(status))
            for index, status in enumerate(OPERATIONAL_STATUSES)
        ]
    if kind == "co":
        return country_picker_items()
    return []


def picker_columns(kind: str, items: list[tuple[int, str]]) -> int:
    if kind in {"st", "acc", "tm"}:
        return 1
    if any(len(label) > 16 for _, label in items):
        return 1
    return 2


def use_named_picker(kind: str, items: list[tuple[int, str]]) -> bool:
    if kind == "st":
        return True
    if kind == "co":
        return False
    if len(items) <= 4:
        return True
    if len(items) <= NAMED_PICKER_MAX and all(len(label) <= 22 for _, label in items):
        return True
    return False


def picker_page_size(kind: str, items: list[tuple[int, str]]) -> int:
    if use_named_picker(kind, items):
        return max(len(items), 1)
    if kind == "co" or any(len(label) > 18 for _, label in items):
        return PICKER_PAGE_LONG
    return PICKER_PAGE_SHORT


async def country_picker_source(
    repo: ShipmentRepository,
    *,
    query: str | None,
    show_all: bool,
) -> tuple[list[tuple[int, str]], str | None]:
    if query:
        return search_countries(query), None
    if show_all:
        return country_picker_items(), None
    used = await repo.distinct_countries()
    return recent_country_items(used), "Recently used:"


async def current_picker_value(
    *,
    kind: str,
    target: str,
    shipment: dict[str, Any] | None,
    draft: dict[str, Any] | None,
) -> tuple[int | None, str | None]:
    source: dict[str, Any] = shipment if target == "s" and shipment else (draft or {})
    if kind == "acc":
        account_id = source.get("account_id")
        name = source.get("account_name")
        if target == "d" and not name:
            return (int(account_id) if account_id else None, None)
        return (int(account_id) if account_id else None, name)
    if kind == "tm":
        team_id = source.get("client_team_id")
        name = source.get("client_team_name")
        return (int(team_id) if team_id else None, name)
    if kind == "st":
        status = source.get("status") or "preparing"
        try:
            index = OPERATIONAL_STATUSES.index(status)
        except ValueError:
            index = None
        return (index, status_display_label(status))
    if kind == "co":
        value = (source.get("country") or "").strip() or None
        if not value:
            return (None, None)
        index = CODE_INDEX.get(value.upper())
        return (index, format_country_label(value))
    return (None, None)


def view_calendar(
    *,
    field: str,
    target: str,
    shipment_id: int,
    year: int,
    month: int,
    current: str | None,
    tz_name: str,
) -> View:
    today = app_today(tz_name)
    selected = None
    iso = extract_date_component(current)
    if iso:
        selected = date.fromisoformat(iso)
    title = DATE_TITLES.get(field, "DATE")
    return View(
        fmt.format_calendar(title=title, current=current, today=today),
        calendar_keyboard(
            field=field,
            target=target,
            shipment_id=shipment_id,
            year=year,
            month=month,
            selected=selected,
            allow_clear=True,
        ),
        "calendar",
    )


async def view_search_results(
    repo: ShipmentRepository,
    query: str,
    page: int,
    *,
    tz_name: str,
) -> View:
    today = app_today(tz_name)
    items, total, page, pages = await _paged_filtered(
        repo, page, query=query, archived=False
    )
    return View(
        fmt.format_search_results(
            query,
            items=items,
            total=total,
            page=page,
            pages=pages,
            today=today,
            page_size=PAGE_SIZE,
        ),
        shipment_list_keyboard(
            items,
            page=page,
            pages=pages,
            nav_page_cb=lambda p: NavCB(x="sp", p=p).pack(),
        ),
        "search",
    )


async def view_all(
    repo: ShipmentRepository,
    *,
    status: str | None,
    page: int,
    tz_name: str,
) -> View:
    today = app_today(tz_name)
    counts = await repo.count_by_status(archived=False)
    if status:
        fetched, _total = await repo.list_filtered(
            status=status, archived=False, limit=200, offset=0
        )
        ordered = sort_by_edd(fetched)
        items, page, pages = _page_items(ordered, page, PAGE_SIZE)
        total = len(ordered)
        title = f"{status_emoji(status)} {STATUS_DISPLAY_LABELS.get(status, status).upper()}"
        filter_label = STATUS_DISPLAY_LABELS.get(status, status)
        short = STATUS_SHORT.get(status, "")
    else:
        shipments = await repo.list_active()
        items, page, pages, total = page_active_shipments(
            shipments, page, size=PAGE_SIZE
        )
        title = "📦 ACTIVE SHIPMENTS"
        filter_label = "All"
        short = ""
    extra = all_filter_rows(counts, current=status or "", page_status=short)
    return View(
        fmt.format_list(
            title=title,
            filter_label=filter_label,
            total=total,
            items=items,
            page=page,
            pages=pages,
            today=today,
            page_size=PAGE_SIZE,
        ),
        shipment_list_keyboard(
            items,
            page=page,
            pages=pages,
            nav_page_cb=lambda p, s=short: NavCB(x="al", p=p, f=s).pack(),
            extra_rows=extra,
        ),
        "list",
    )


async def view_accounts(accounts: AccountRepository, page: int = 0) -> View:
    rows = await accounts.summary()
    unassigned = [row for row in rows if row.get("id") is None or row.get("unassigned")]
    named = [row for row in rows if not (row.get("id") is None or row.get("unassigned"))]
    ordered = unassigned + named
    picker_items = [
        (int(row["id"]) if row.get("id") is not None else 0, str(row.get("name") or "No account"))
        for row in ordered
    ]
    use_named = use_named_picker("acc", picker_items)
    if use_named:
        return View(
            fmt.format_accounts(ordered, numbered=False),
            accounts_keyboard(ordered, numeric=False),
            "accounts",
        )
    page_items, page, pages = _page_items(ordered, page, ACCOUNTS_PAGE_SIZE)
    return View(
        fmt.format_accounts(
            page_items,
            numbered=True,
            page=page,
            pages=pages,
            total=len(ordered),
            page_size=ACCOUNTS_PAGE_SIZE,
        ),
        accounts_keyboard(page_items, numeric=True, page=page, pages=pages),
        "accounts",
    )


async def view_account_shipments(
    repo: ShipmentRepository,
    *,
    account_id: int | None,
    unassigned: bool,
    page: int,
    tz_name: str,
    title: str,
) -> View:
    today = app_today(tz_name)
    items, total, page, pages = await _paged_filtered(
        repo,
        page,
        account_id=None if unassigned else account_id,
        unassigned_account=unassigned,
        archived=False,
    )
    flag = "u" if unassigned else ""
    aid = 0 if unassigned else int(account_id or 0)
    return View(
        fmt.format_list(
            title=f"👤 {title}",
            filter_label="All",
            total=total,
            items=items,
            page=page,
            pages=pages,
            today=today,
            page_size=PAGE_SIZE,
        ),
        shipment_list_keyboard(
            items,
            page=page,
            pages=pages,
            nav_page_cb=lambda p, a=aid, f=flag: NavCB(x="ah", p=p, i=a, f=f).pack(),
        ),
        "acct_ships",
    )


async def view_archive(
    repo: ShipmentRepository,
    page: int,
    *,
    tz_name: str,
) -> View:
    today = app_today(tz_name)
    items, total, page, pages = await _paged_filtered(repo, page, archived=True)
    return View(
        fmt.format_list(
            title="🗄 ARCHIVE",
            filter_label="Archived",
            total=total,
            items=items,
            page=page,
            pages=pages,
            today=today,
            page_size=PAGE_SIZE,
        ),
        shipment_list_keyboard(
            items,
            page=page,
            pages=pages,
            nav_page_cb=lambda p: NavCB(x="ar", p=p).pack(),
        ),
        "archive",
    )


async def view_history(
    repo: ShipmentRepository,
    shipment_id: int,
    page: int,
) -> View | None:
    shipment = await repo.get_by_id(shipment_id)
    if shipment is None:
        return None
    events = await repo.list_history(shipment_id)
    page_items, page, pages = _page_items(events, page, PAGE_SIZE)
    builder = InlineKeyboardBuilder()
    if pages > 1:
        builder.row(
            InlineKeyboardButton(
                text="‹",
                callback_data=ShipCB(x="hi", i=shipment_id, p=max(0, page - 1)).pack(),
            ),
            InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data=NavCB(x="np").pack()),
            InlineKeyboardButton(
                text="›",
                callback_data=ShipCB(x="hi", i=shipment_id, p=min(pages - 1, page + 1)).pack(),
            ),
        )
    builder.row(InlineKeyboardButton(text="← Back", callback_data=NavCB(x="bk").pack()))
    return View(fmt.format_history(shipment, page_items), builder.as_markup(), "history")


async def view_reminder(repo: ShipmentRepository, shipment_id: int, *, tz_name: str) -> View | None:
    shipment = await repo.get_by_id(shipment_id)
    if shipment is None:
        return None
    reminder = await repo.get_active_reminder(shipment_id)
    current = None
    if reminder:
        current = fmt.format_reminder_at(reminder.get("remind_at"), tz_name=tz_name)
    return View(
        fmt.format_reminder(shipment, current),
        reminder_keyboard(shipment_id, has_reminder=reminder is not None),
        "reminder",
    )


def view_reminder_time(shipment_id: int, when: date) -> View:
    return View(
        f"<b>🕒 REMINDER TIME</b>\n\n{fmt.format_human_date(when.isoformat(), with_year=True)}",
        reminder_time_keyboard(shipment_id, year=when.year, month=when.month, day=when.day),
        "reminder_time",
    )


def view_archive_confirm(shipment: dict[str, Any]) -> View:
    return View(
        fmt.format_archive_confirm(shipment),
        confirm_keyboard(
            yes=ShipCB(x="ay", i=int(shipment["id"])).pack(),
            yes_text="🗄 Archive",
        ),
        "confirm",
    )


def view_delivered_confirm(shipment: dict[str, Any]) -> View:
    return View(
        fmt.format_delivered_confirm(shipment),
        confirm_keyboard(
            yes=ShipCB(x="my", i=int(shipment["id"])).pack(),
            yes_text="✅ Yes, delivered",
        ),
        "confirm",
    )


def view_search_prompt() -> View:
    return View(fmt.format_search_prompt(), input_cancel_keyboard(), "input")


def view_unit_quantity_prompt(current: Any, *, target: str, shipment_id: int) -> View:
    return View(
        fmt.format_unit_quantity_prompt(current),
        unit_quantity_input_keyboard(target, shipment_id),
        "input",
    )


def view_note_prompt() -> View:
    return View(fmt.format_note_prompt(), input_back_keyboard(), "input")


def view_name_prompt(current: str | None = None) -> View:
    return View(fmt.format_name_prompt(current), input_back_keyboard(), "input")


def view_new_account_prompt() -> View:
    return View(fmt.format_new_account_prompt(), input_cancel_keyboard(), "input")


def view_new_team_prompt() -> View:
    return View(fmt.format_new_team_prompt(), input_cancel_keyboard(), "input")


def view_new_value_prompt(kind: str) -> View:
    return View(fmt.format_new_value_prompt(kind), input_cancel_keyboard(), "input")


def view_picker_search_prompt(kind: str) -> View:
    label = PICKER_TITLES.get(kind, "SEARCH")
    hint = "Type a country name or ISO code, e.g. Germany or DE." if kind == "co" else "Type part of the name to filter."
    return View(
        f"<b>🔎 {fmt.esc(label)}</b>\n\n{hint}",
        input_cancel_keyboard(),
        "input",
    )


# Silence unused import warning in type checkers for draft_missing re-export
__all__ = ["View", "draft_missing", "view_home", "view_details", "view_draft"]
