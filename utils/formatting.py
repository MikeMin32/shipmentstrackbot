"""Status constants and HTML formatting helpers."""

from __future__ import annotations

from html import escape
from typing import Any

from utils.timefmt import format_utc_display

# Stable internal status values (order used in status pickers / By Status)
STATUSES: tuple[str, ...] = (
    "standby",
    "preparing",
    "make_label",
    "enroute",
    "out_for_delivery",
)

# Summary list: standby has no emoji (client style)
STATUS_EMOJI: dict[str, str] = {
    "standby": "",
    "preparing": "📦",
    "make_label": "📝",
    "enroute": "✈️",
    "out_for_delivery": "🚚",
}

# Select Shipment grid: every status gets a visible emoji
SELECTOR_STATUS_EMOJI: dict[str, str] = {
    "standby": "⚪",
    "preparing": "📦",
    "make_label": "📝",
    "enroute": "✈️",
    "out_for_delivery": "🚚",
}

STATUS_LABELS: dict[str, str] = {
    "standby": "Standby",
    "preparing": "📦 Preparing",
    "make_label": "📝 Make Label",
    "enroute": "✈️ EnRoute",
    "out_for_delivery": "🚚 Out For Delivery",
}

WORKING_STATUSES: tuple[str, ...] = (
    "preparing",
    "make_label",
    "out_for_delivery",
    "standby",
)

DEFAULT_STATUS = "preparing"


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def status_emoji(status: str) -> str:
    return STATUS_EMOJI.get(status, "")


def selector_status_emoji(status: str) -> str:
    return SELECTOR_STATUS_EMOJI.get(status, "⚪")


def esc(value: Any) -> str:
    """Escape user-controlled text for HTML parse mode."""
    if value is None:
        return ""
    return escape(str(value))


def shipment_title(shipment: dict[str, Any]) -> str:
    """Human title: 'DE : Oner'."""
    country = (shipment.get("country") or "").strip()
    clone = (shipment.get("clone_name") or "").strip()
    if country and clone:
        return f"{country} : {clone}"
    if clone:
        return clone
    if country:
        return country
    legacy = (shipment.get("display_name") or "").strip()
    if legacy:
        return legacy
    return f"#{shipment.get('id', '?')}"


def shipment_edd_raw(shipment: dict[str, Any]) -> str | None:
    value = shipment.get("expected_delivery_date") or shipment.get("expected_date")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def format_shipment_line(shipment: dict[str, Any]) -> str:
    """One summary line: • DE : Oner ✈️ — 2026-08-09 18:00 UTC."""
    title = esc(shipment_title(shipment))
    emoji = status_emoji(shipment.get("status", ""))
    edd = shipment_edd_raw(shipment)

    if emoji:
        line = f"• {title} {emoji}"
    else:
        line = f"• {title}"

    if edd:
        line = f"{line} — {esc(format_utc_display(edd))}"
    return line


def format_active_list(shipments: list[dict[str, Any]]) -> str:
    """Main summary: EnRoute first, then Working On / Standby."""
    if not shipments:
        return (
            "📦 <b>Shipments</b>\n\n"
            "No active shipments yet.\n"
            "Use ➕ Add to create one."
        )

    enroute: list[dict[str, Any]] = []
    working: list[dict[str, Any]] = []
    for item in shipments:
        if item.get("status") == "enroute":
            enroute.append(item)
        else:
            working.append(item)

    working.sort(
        key=lambda item: (
            WORKING_STATUSES.index(item["status"])
            if item.get("status") in WORKING_STATUSES
            else 99,
            item.get("id") or 0,
        )
    )
    enroute.sort(key=lambda item: item.get("id") or 0)

    parts = ["📦 <b>Shipments</b>"]
    if enroute:
        parts.append("")
        parts.append("<b>✈️ EnRoute:</b>")
        for item in enroute:
            parts.append(format_shipment_line(item))
    if working:
        parts.append("")
        parts.append("<b>Working On / Standby:</b>")
        for item in working:
            parts.append(format_shipment_line(item))
    return "\n".join(parts)


def format_status_list(counts: dict[str, int]) -> str:
    lines = ["<b>📦 By Status</b>", ""]
    for status in STATUSES:
        count = counts.get(status, 0)
        lines.append(f"{status_label(status)} ({count})")
    return "\n".join(lines)


def format_status_shipments(status: str, shipments: list[dict[str, Any]]) -> str:
    label = status_label(status)
    if not shipments:
        return f"<b>{label}</b>\n\nNo shipments with this status."
    lines = [f"<b>{label}</b>", ""]
    for item in shipments:
        lines.append(format_shipment_line(item))
    return "\n".join(lines)


def format_details(
    shipment: dict[str, Any],
    *,
    reminder_text: str | None = None,
) -> str:
    note = shipment.get("note") or "—"
    edd = format_utc_display(shipment_edd_raw(shipment))
    updated = shipment.get("updated_at") or "—"
    reminder = reminder_text or "—"
    return (
        "<b>📦 Shipment</b>\n\n"
        f"Country: {esc(shipment.get('country') or '—')}\n"
        f"Clone: {esc(shipment.get('clone_name') or '—')}\n"
        f"Status: {status_label(shipment['status'])}\n"
        f"EDD: {esc(edd)}\n"
        f"Reminder: {esc(reminder)}\n"
        f"Note: {esc(note)}\n"
        f"Updated: {esc(updated)}"
    )


def format_search_results(query: str, shipments: list[dict[str, Any]]) -> str:
    if not shipments:
        return f"No active shipments matching <b>{esc(query)}</b>."
    return f"Results for <b>{esc(query)}</b>:"


def format_reminder_notice(shipment: dict[str, Any]) -> str:
    edd = format_utc_display(shipment_edd_raw(shipment))
    return (
        "⏰ <b>Shipment Reminder</b>\n\n"
        f"{esc(shipment_title(shipment))}\n"
        f"Status: {status_label(shipment['status'])}\n"
        f"EDD: {esc(edd)}\n\n"
        "This shipment is due soon."
    )


def format_reminder_menu(shipment: dict[str, Any], reminder_text: str | None) -> str:
    edd = format_utc_display(shipment_edd_raw(shipment))
    current = reminder_text or "—"
    return (
        "⏰ <b>Shipment Reminder</b>\n\n"
        f"{esc(shipment_title(shipment))}\n"
        f"EDD: {esc(edd)}\n"
        f"Reminder: {esc(current)}"
    )
