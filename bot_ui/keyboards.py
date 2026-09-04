"""Inline keyboards for the workspace UI."""

from __future__ import annotations

from datetime import date
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_ui.calendar import WEEKDAYS, month_title, month_weeks
from bot_ui.callbacks import DateCB, NavCB, OpenCB, PickCB, RemCB, ShipCB
from bot_ui.format import truncate_button
from domain.status import (
    OPERATIONAL_STATUSES,
    STATUS_DISPLAY_LABELS,
    STATUS_SHORT,
)
from utils.dates import extract_date_component

HOME_PAGE_SIZE = 9
PAGE_SIZE = 9
PICKER_PAGE_SHORT = 8
PICKER_PAGE_LONG = 6
NAMED_PICKER_MAX = 6
ACCOUNTS_PAGE_SIZE = 8


def _nav(x: str, *, p: int = 0, i: int = 0, f: str = "") -> str:
    return NavCB(x=x, p=p, i=i, f=f).pack()


def _ship(x: str, shipment_id: int, *, p: int = 0) -> str:
    return ShipCB(x=x, i=shipment_id, p=p).pack()


def _pick(
    x: str,
    kind: str,
    target: str,
    *,
    shipment_id: int = 0,
    page: int = 0,
    n: int = 0,
) -> str:
    return PickCB(x=x, k=kind, t=target, i=shipment_id, p=page, n=n).pack()


def _date(
    x: str,
    field: str,
    target: str,
    *,
    shipment_id: int = 0,
    year: int = 0,
    month: int = 0,
    n: int = 0,
) -> str:
    return DateCB(x=x, f=field, t=target, i=shipment_id, y=year, m=month, n=n).pack()


def _pager(
    page: int,
    pages: int,
    prev_data: str,
    next_data: str,
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="‹", callback_data=prev_data),
        InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data=_nav("np")),
        InlineKeyboardButton(text="›", callback_data=next_data),
    ]


def add_numeric_grid(
    builder: InlineKeyboardBuilder,
    items: list[tuple[str, str]],
    *,
    columns: int,
) -> None:
    row: list[InlineKeyboardButton] = []
    for text, callback_data in items:
        row.append(InlineKeyboardButton(text=text, callback_data=callback_data))
        if len(row) == columns:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)


def home_keyboard(
    shipments: list[dict[str, Any]],
    *,
    total_active: int,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    add_numeric_grid(
        builder,
        [
            (str(index), _ship("vw", int(item["id"])))
            for index, item in enumerate(shipments, start=1)
        ],
        columns=3,
    )
    if pages > 1:
        builder.row(
            *_pager(
                page,
                pages,
                _nav("hp", p=max(0, page - 1)),
                _nav("hp", p=min(pages - 1, page + 1)),
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ Add", callback_data=_nav("ad")),
        InlineKeyboardButton(text="🔎 Search", callback_data=_nav("se")),
    )
    builder.row(
        InlineKeyboardButton(text=f"📦 All · {total_active}", callback_data=_nav("al")),
        InlineKeyboardButton(text="📊 Accounts", callback_data=_nav("as")),
    )
    builder.row(
        InlineKeyboardButton(text="🗄 Archive", callback_data=_nav("ar")),
        InlineKeyboardButton(text="🔄 Refresh", callback_data=_nav("rf")),
    )
    return builder.as_markup()


def details_keyboard(shipment: dict[str, Any]) -> InlineKeyboardMarkup:
    sid = int(shipment["id"])
    archived = bool(shipment.get("archived"))
    delivered = shipment.get("status") == "delivered"
    builder = InlineKeyboardBuilder()
    if not archived:
        builder.row(InlineKeyboardButton(text="📦 Status", callback_data=_ship("st", sid)))
        builder.row(
            InlineKeyboardButton(text="✏️ Name", callback_data=_ship("nm", sid)),
            InlineKeyboardButton(text="🌍 Country", callback_data=_pick("o", "co", "s", shipment_id=sid)),
        )
        builder.row(
            InlineKeyboardButton(text="🏢 Account", callback_data=_pick("o", "acc", "s", shipment_id=sid)),
            InlineKeyboardButton(text="👥 Team", callback_data=_pick("o", "tm", "s", shipment_id=sid)),
        )
        builder.row(
            InlineKeyboardButton(text="⚖️ Weight", callback_data=_ship("wt", sid)),
            InlineKeyboardButton(text="📝 Note", callback_data=_ship("nt", sid)),
        )
        builder.row(
            InlineKeyboardButton(text="🏷 Label", callback_data=_date("m", "lb", "s", shipment_id=sid)),
            InlineKeyboardButton(text="📥 Scanned", callback_data=_date("m", "sc", "s", shipment_id=sid)),
        )
        builder.row(
            InlineKeyboardButton(text="🚚 Expected", callback_data=_date("m", "ed", "s", shipment_id=sid)),
            InlineKeyboardButton(text="⏰ Reminder", callback_data=RemCB(x="m", i=sid).pack()),
        )
        if not delivered:
            builder.row(InlineKeyboardButton(text="✅ Mark Delivered", callback_data=_ship("md", sid)))
        builder.row(InlineKeyboardButton(text="🗄 Archive", callback_data=_ship("aq", sid)))
    else:
        builder.row(InlineKeyboardButton(text="♻️ Restore", callback_data=_ship("rs", sid)))
    builder.row(
        InlineKeyboardButton(text="📜 History", callback_data=_ship("hi", sid)),
        InlineKeyboardButton(text="← Back", callback_data=_nav("bk")),
    )
    return builder.as_markup()


def draft_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Name", callback_data=_nav("nm")),
        InlineKeyboardButton(text="🌍 Country", callback_data=_pick("o", "co", "d")),
    )
    builder.row(
        InlineKeyboardButton(text="🏢 Account", callback_data=_pick("o", "acc", "d")),
        InlineKeyboardButton(text="👥 Team", callback_data=_pick("o", "tm", "d")),
    )
    builder.row(
        InlineKeyboardButton(text="⚖️ Weight", callback_data=_nav("wt")),
        InlineKeyboardButton(text="📦 Status", callback_data=_pick("o", "st", "d")),
    )
    builder.row(
        InlineKeyboardButton(text="🏷 Label", callback_data=_date("m", "lb", "d")),
        InlineKeyboardButton(text="📥 Scanned", callback_data=_date("m", "sc", "d")),
    )
    builder.row(
        InlineKeyboardButton(text="🚚 Expected", callback_data=_date("m", "ed", "d")),
        InlineKeyboardButton(text="📝 Note", callback_data=_nav("nt")),
    )
    builder.row(InlineKeyboardButton(text="✅ Create shipment", callback_data=_nav("cr")))
    builder.row(InlineKeyboardButton(text="✕ Cancel", callback_data=_nav("cx")))
    return builder.as_markup()


def picker_keyboard(
    *,
    kind: str,
    target: str,
    shipment_id: int,
    items: list[tuple[int, str]],
    page: int,
    pages: int,
    current_id: int | None,
    allow_new: bool,
    allow_search: bool,
    allow_clear: bool,
    columns: int,
    numeric: bool,
    extra_nav: list[InlineKeyboardButton] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if numeric:
        add_numeric_grid(
            builder,
            [
                (
                    str(index),
                    _pick("s", kind, target, shipment_id=shipment_id, page=page, n=item_id),
                )
                for index, (item_id, _label) in enumerate(items, start=1)
            ],
            columns=2,
        )
    else:
        for item_id, label in items:
            mark = "✓ " if current_id is not None and item_id == current_id else ""
            builder.button(
                text=truncate_button(f"{mark}{label}"),
                callback_data=_pick("s", kind, target, shipment_id=shipment_id, page=page, n=item_id),
            )
        builder.adjust(max(1, columns))
    if pages > 1:
        builder.row(
            *_pager(
                page,
                pages,
                _pick("g", kind, target, shipment_id=shipment_id, page=max(0, page - 1)),
                _pick(
                    "g",
                    kind,
                    target,
                    shipment_id=shipment_id,
                    page=min(pages - 1, page + 1),
                ),
            )
        )
    extras: list[InlineKeyboardButton] = []
    if allow_search:
        extras.append(
            InlineKeyboardButton(
                text="🔎 Search",
                callback_data=_pick("q", kind, target, shipment_id=shipment_id, page=page),
            )
        )
    if allow_new:
        extras.append(
            InlineKeyboardButton(
                text="➕ New",
                callback_data=_pick("n", kind, target, shipment_id=shipment_id),
            )
        )
    if extras:
        builder.row(*extras)
    if extra_nav:
        builder.row(*extra_nav)
    if allow_clear:
        builder.row(
            InlineKeyboardButton(
                text="Clear",
                callback_data=_pick("c", kind, target, shipment_id=shipment_id),
            ),
            InlineKeyboardButton(text="← Back", callback_data=_nav("bk")),
        )
    else:
        builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
    return builder.as_markup()


def calendar_keyboard(
    *,
    field: str,
    target: str,
    shipment_id: int,
    year: int,
    month: int,
    selected: date | None,
    allow_clear: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="‹",
            callback_data=_date("n", field, target, shipment_id=shipment_id, year=year, month=month, n=-1),
        ),
        InlineKeyboardButton(
            text=month_title(year, month),
            callback_data=_nav("np"),
        ),
        InlineKeyboardButton(
            text="›",
            callback_data=_date("n", field, target, shipment_id=shipment_id, year=year, month=month, n=1),
        ),
    )
    builder.row(
        *[
            InlineKeyboardButton(text=label, callback_data=_nav("np"))
            for label in WEEKDAYS
        ]
    )
    for week in month_weeks(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day is None:
                row.append(InlineKeyboardButton(text=" ", callback_data=_nav("np")))
                continue
            label = str(day.day)
            if selected and day == selected:
                label = f"[{day.day}]"
            row.append(
                InlineKeyboardButton(
                    text=label,
                    callback_data=_date(
                        "s",
                        field,
                        target,
                        shipment_id=shipment_id,
                        year=day.year,
                        month=day.month,
                        n=day.day,
                    ),
                )
            )
        builder.row(*row)
    if field == "rm":
        builder.row(
            InlineKeyboardButton(text="Today", callback_data=_date("q", field, target, shipment_id=shipment_id, n=0)),
            InlineKeyboardButton(text="Tomorrow", callback_data=_date("q", field, target, shipment_id=shipment_id, n=1)),
        )
        if allow_clear:
            builder.row(
                InlineKeyboardButton(
                    text="Clear",
                    callback_data=_date("c", field, target, shipment_id=shipment_id),
                )
            )
        builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
        return builder.as_markup()
    builder.row(
        InlineKeyboardButton(text="Today", callback_data=_date("q", field, target, shipment_id=shipment_id, n=0)),
    )
    if allow_clear:
        builder.row(
            InlineKeyboardButton(
                text="Clear",
                callback_data=_date("c", field, target, shipment_id=shipment_id),
            ),
            InlineKeyboardButton(text="← Back", callback_data=_nav("bk")),
        )
    else:
        builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
    return builder.as_markup()


def shipment_list_keyboard(
    shipments: list[dict[str, Any]],
    *,
    page: int,
    pages: int,
    nav_page_cb,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if extra_rows:
        for row in extra_rows:
            builder.row(*row)
    add_numeric_grid(
        builder,
        [
            (str(index), _ship("vw", int(item["id"])))
            for index, item in enumerate(shipments, start=1)
        ],
        columns=3,
    )
    if pages > 1:
        builder.row(
            *_pager(
                page,
                pages,
                nav_page_cb(max(0, page - 1)),
                nav_page_cb(min(pages - 1, page + 1)),
            )
        )
    builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
    return builder.as_markup()


def all_filter_rows(counts: dict[str, int], *, current: str, page_status: str) -> list[list[InlineKeyboardButton]]:
    del page_status
    active_total = sum(counts.get(status, 0) for status in OPERATIONAL_STATUSES)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"All {active_total}",
                callback_data=_nav("al", f=""),
            )
        ]
    ]
    chunk: list[InlineKeyboardButton] = []
    for status in OPERATIONAL_STATUSES:
        count = counts.get(status, 0)
        label = STATUS_DISPLAY_LABELS[status]
        mark = "· " if current == status else ""
        chunk.append(
            InlineKeyboardButton(
                text=truncate_button(f"{mark}{label} {count}", 32),
                callback_data=_nav("al", f=STATUS_SHORT[status]),
            )
        )
        if len(chunk) == 2:
            rows.append(chunk)
            chunk = []
    if chunk:
        rows.append(chunk)
    return rows


def accounts_keyboard(
    rows: list[dict[str, Any]],
    *,
    numeric: bool,
    page: int = 0,
    pages: int = 1,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons: list[tuple[str, str]] = []
    for index, row in enumerate(rows, start=1):
        unassigned = 1 if row.get("id") is None or row.get("unassigned") else 0
        account_id = int(row["id"]) if row.get("id") is not None else 0
        data = _nav("ah", i=account_id, f="u" if unassigned else "")
        if numeric:
            buttons.append((str(index), data))
        else:
            name = row.get("name") or "No account"
            builder.row(InlineKeyboardButton(text=truncate_button(str(name)), callback_data=data))
    if numeric:
        add_numeric_grid(builder, buttons, columns=2)
    if pages > 1:
        builder.row(
            *_pager(
                page,
                pages,
                _nav("as", p=max(0, page - 1)),
                _nav("as", p=min(pages - 1, page + 1)),
            )
        )
    builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
    return builder.as_markup()


def confirm_keyboard(*, yes: str, yes_text: str, no: str = "bk") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=yes_text, callback_data=yes))
    builder.row(InlineKeyboardButton(text="Cancel", callback_data=_nav(no) if no == "bk" else no))
    return builder.as_markup()


def reminder_keyboard(shipment_id: int, *, has_reminder: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="In 1 hour", callback_data=RemCB(x="q", i=shipment_id, n=1).pack()))
    builder.row(
        InlineKeyboardButton(text="Today 18:00", callback_data=RemCB(x="q", i=shipment_id, n=2).pack()),
        InlineKeyboardButton(text="Tomorrow 09:00", callback_data=RemCB(x="q", i=shipment_id, n=3).pack()),
    )
    builder.row(
        InlineKeyboardButton(text="Tomorrow 12:00", callback_data=RemCB(x="q", i=shipment_id, n=4).pack()),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Pick date", callback_data=RemCB(x="d", i=shipment_id).pack()),
        InlineKeyboardButton(text="🕒 Pick time", callback_data=RemCB(x="t", i=shipment_id).pack()),
    )
    if has_reminder:
        builder.row(InlineKeyboardButton(text="Remove reminder", callback_data=RemCB(x="x", i=shipment_id).pack()))
    builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
    return builder.as_markup()


REMINDER_HOURS = (8, 9, 10, 12, 15, 18, 20)


def reminder_time_keyboard(shipment_id: int, *, year: int, month: int, day: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for hour in REMINDER_HOURS:
        row.append(
            InlineKeyboardButton(
                text=f"{hour:02d}:00",
                callback_data=RemCB(x="s", i=shipment_id, n=hour, y=year, m=month, d=day).pack(),
            )
        )
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("bk")))
    return builder.as_markup()


def input_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Cancel", callback_data=_nav("ic")))
    return builder.as_markup()


def input_back_keyboard(*, extra: InlineKeyboardButton | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if extra:
        builder.row(extra)
    builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("ic")))
    return builder.as_markup()


def weight_input_keyboard(target: str, shipment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if target == "s":
        builder.row(
            InlineKeyboardButton(text="Clear", callback_data=_ship("w0", shipment_id))
        )
    else:
        builder.row(InlineKeyboardButton(text="Clear", callback_data=_nav("w0")))
    builder.row(InlineKeyboardButton(text="← Back", callback_data=_nav("ic")))
    return builder.as_markup()


def open_shipment_keyboard(shipment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Open Shipment", callback_data=OpenCB(i=shipment_id).pack())
    return builder.as_markup()


def iso_from_shipment_field(shipment: dict[str, Any], field: str) -> str | None:
    mapping = {
        "lb": "label_creation_date",
        "sc": "scanned_in_date",
        "ed": "expected_delivery_date",
    }
    key = mapping.get(field)
    if not key:
        return None
    raw = shipment.get(key)
    if field == "ed":
        raw = raw or shipment.get("expected_date")
    return extract_date_component(raw)
