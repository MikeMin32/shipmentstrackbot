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

# Operational groupings for the Mini App (display logic only).
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


def status_group(status: str) -> str:
    if status in WORKING_STATUSES:
        return "working"
    if status in IN_TRANSIT_STATUSES:
        return "in_transit"
    if status in COMPLETED_STATUSES:
        return "completed"
    return "other"
