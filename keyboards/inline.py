"""Inline keyboards and CallbackData factories."""

from __future__ import annotations

from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.formatting import (
    STATUSES,
    selector_status_emoji,
    shipment_title,
    status_label,
)


class MenuCB(CallbackData, prefix="menu"):
    action: str


class ShipmentCB(CallbackData, prefix="shp"):
    action: str
    shipment_id: int = 0
    value: str = ""


class StatusCB(CallbackData, prefix="sts"):
    action: str
    status: str = ""


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Active Shipments", callback_data=MenuCB(action="active").pack())
    builder.button(text="➕ Add Shipment", callback_data=MenuCB(action="add").pack())
    builder.button(text="🔎 Search", callback_data=MenuCB(action="search").pack())
    builder.button(text="📦 By Status", callback_data=MenuCB(action="by_status").pack())
    builder.adjust(1)
    return builder.as_markup()


def active_summary_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔎 Select Shipment",
            callback_data=MenuCB(action="select").pack(),
        ),
        InlineKeyboardButton(
            text="➕ Add",
            callback_data=MenuCB(action="add").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Refresh",
            callback_data=MenuCB(action="active").pack(),
        ),
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=MenuCB(action="home").pack(),
        ),
    )
    return builder.as_markup()


def active_list_keyboard(_shipments: list[dict[str, Any]] | None = None) -> InlineKeyboardMarkup:
    return active_summary_keyboard()


def select_shipment_keyboard(shipments: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in shipments:
        emoji = selector_status_emoji(item.get("status", ""))
        title = shipment_title(item)
        text = f"{emoji} {title}".strip()
        if len(text) > 30:
            text = text[:27] + "..."
        builder.button(
            text=text,
            callback_data=ShipmentCB(action="view", shipment_id=item["id"]).pack(),
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=MenuCB(action="active").pack(),
        )
    )
    return builder.as_markup()


def shipment_details_keyboard(shipment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🌍 Country",
            callback_data=ShipmentCB(action="edit_country", shipment_id=shipment_id).pack(),
        ),
        InlineKeyboardButton(
            text="👤 Clone Name",
            callback_data=ShipmentCB(action="edit_clone", shipment_id=shipment_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Status",
            callback_data=ShipmentCB(action="status", shipment_id=shipment_id).pack(),
        ),
        InlineKeyboardButton(
            text="📅 EDD",
            callback_data=ShipmentCB(action="edd", shipment_id=shipment_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📝 Note",
            callback_data=ShipmentCB(action="note", shipment_id=shipment_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⏰ Reminder",
            callback_data=ShipmentCB(action="reminder", shipment_id=shipment_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Complete",
            callback_data=ShipmentCB(action="complete", shipment_id=shipment_id).pack(),
        ),
        InlineKeyboardButton(
            text="🗑 Archive",
            callback_data=ShipmentCB(action="archive", shipment_id=shipment_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=MenuCB(action="active").pack(),
        )
    )
    return builder.as_markup()


def reminder_menu_keyboard(
    shipment_id: int,
    *,
    has_reminder: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Set Reminder",
            callback_data=ShipmentCB(action="rem_set", shipment_id=shipment_id).pack(),
        )
    )
    if has_reminder:
        builder.row(
            InlineKeyboardButton(
                text="🗑 Remove Reminder",
                callback_data=ShipmentCB(action="rem_remove", shipment_id=shipment_id).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=ShipmentCB(action="view", shipment_id=shipment_id).pack(),
        )
    )
    return builder.as_markup()


def open_shipment_keyboard(shipment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📦 Open Shipment",
        callback_data=ShipmentCB(action="view", shipment_id=shipment_id).pack(),
    )
    return builder.as_markup()


def status_picker_keyboard(
    *,
    shipment_id: int | None = None,
    cancel_action: str = "cancel_status",
    for_create: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for status in STATUSES:
        if status == "delivered" and for_create:
            continue
        if for_create:
            callback = ShipmentCB(action="create_status", value=status).pack()
        else:
            assert shipment_id is not None
            callback = ShipmentCB(
                action="set_status",
                shipment_id=shipment_id,
                value=status,
            ).pack()
        builder.button(text=status_label(status), callback_data=callback)
    builder.adjust(1)

    if for_create:
        builder.row(
            InlineKeyboardButton(
                text="⬅️ Cancel",
                callback_data=MenuCB(action="home").pack(),
            )
        )
    else:
        assert shipment_id is not None
        builder.row(
            InlineKeyboardButton(
                text="⬅️ Cancel",
                callback_data=ShipmentCB(
                    action=cancel_action,
                    shipment_id=shipment_id,
                ).pack(),
            )
        )
    return builder.as_markup()


def archive_confirm_keyboard(shipment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Yes",
        callback_data=ShipmentCB(action="archive_yes", shipment_id=shipment_id).pack(),
    )
    builder.button(
        text="❌ Cancel",
        callback_data=ShipmentCB(action="archive_no", shipment_id=shipment_id).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def by_status_keyboard(counts: dict[str, int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for status in STATUSES:
        count = counts.get(status, 0)
        builder.button(
            text=f"{status_label(status)} ({count})",
            callback_data=StatusCB(action="list", status=status).pack(),
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=MenuCB(action="home").pack(),
        )
    )
    return builder.as_markup()


def status_shipments_keyboard(
    status: str,
    shipments: list[dict[str, Any]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in shipments:
        text = shipment_title(item)
        if len(text) > 28:
            text = text[:25] + "..."
        builder.button(
            text=text,
            callback_data=ShipmentCB(action="view", shipment_id=item["id"]).pack(),
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=MenuCB(action="by_status").pack(),
        )
    )
    return builder.as_markup()


def search_results_keyboard(shipments: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in shipments:
        text = shipment_title(item)
        if len(text) > 28:
            text = text[:25] + "..."
        builder.button(
            text=text,
            callback_data=ShipmentCB(action="view", shipment_id=item["id"]).pack(),
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text="🔎 Search again",
            callback_data=MenuCB(action="search").pack(),
        ),
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=MenuCB(action="home").pack(),
        ),
    )
    return builder.as_markup()
