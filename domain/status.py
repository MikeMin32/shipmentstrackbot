"""Shipment status values, display labels, and operational groupings.

Internal status strings are stored in SQLite and must remain stable.
"""

from __future__ import annotations

# Stable internal status values. Existing records use these strings.
STATUSES: tuple[str, ...] = (
    "standby",
    "preparing",
    "make_label",
    "enroute",
    "out_for_delivery",
    "delivered",
)

DEFAULT_STATUS = "preparing"
DELIVERED_STATUS = "delivered"

WORKING_STATUSES: tuple[str, ...] = (
    "preparing",
    "make_label",
    "standby",
)
IN_TRANSIT_STATUSES: tuple[str, ...] = (
    "enroute",
    "out_for_delivery",
)
COMPLETED_STATUSES: tuple[str, ...] = (DELIVERED_STATUS,)
ACTIVE_STATUSES: tuple[str, ...] = WORKING_STATUSES + IN_TRANSIT_STATUSES

# Status picker order for the Telegram workspace (Delivered is a separate action).
OPERATIONAL_STATUSES: tuple[str, ...] = (
    "preparing",
    "make_label",
    "enroute",
    "out_for_delivery",
    "standby",
)

# Home operational list: outbound first, then in transit, then warehouse work.
HOME_STATUS_ORDER: tuple[str, ...] = (
    "out_for_delivery",
    "enroute",
    "preparing",
    "make_label",
    "standby",
)

STATUS_EMOJI: dict[str, str] = {
    "preparing": "📦",
    "make_label": "🏷️",
    "enroute": "✈️",
    "out_for_delivery": "🚚",
    "standby": "⏸️",
    "delivered": "✅",
}

HOME_SECTION_LABELS: dict[str, str] = {
    "enroute": "EN ROUTE",
    "out_for_delivery": "OUT FOR DELIVERY",
    "preparing": "PREPARING",
    "make_label": "MAKE LABEL",
    "standby": "STANDBY",
}

STATUS_SHORT: dict[str, str] = {
    "preparing": "pr",
    "make_label": "ml",
    "enroute": "er",
    "out_for_delivery": "od",
    "standby": "sb",
    "delivered": "dv",
}
STATUS_FROM_SHORT: dict[str, str] = {value: key for key, value in STATUS_SHORT.items()}

STATUS_DISPLAY_LABELS: dict[str, str] = {
    "standby": "Standby",
    "preparing": "Preparing",
    "make_label": "Make Label",
    "enroute": "En Route",
    "out_for_delivery": "Out For Delivery",
    "delivered": "Delivered",
}

STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "working": WORKING_STATUSES,
    "in_transit": IN_TRANSIT_STATUSES,
    "completed": COMPLETED_STATUSES,
    "active": ACTIVE_STATUSES,
}


def status_display_label(status: str) -> str:
    return STATUS_DISPLAY_LABELS.get(status, status)


def status_emoji(status: str) -> str:
    return STATUS_EMOJI.get(status, "⚪")


def status_line(status: str) -> str:
    return f"{status_emoji(status)} {status_display_label(status)}"


def home_section_label(status: str) -> str:
    return HOME_SECTION_LABELS.get(status, status_display_label(status).upper())


def status_group(status: str) -> str:
    if status in WORKING_STATUSES:
        return "working"
    if status in IN_TRANSIT_STATUSES:
        return "in_transit"
    if status in COMPLETED_STATUSES:
        return "completed"
    return "other"
