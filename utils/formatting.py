"""Status constants and HTML formatting helpers."""

from __future__ import annotations

from html import escape
from typing import Any

from domain.status import (
    DEFAULT_STATUS,
    IN_TRANSIT_STATUSES,
    STATUSES,
    STATUS_EMOJI as DOMAIN_STATUS_EMOJI,
    WORKING_STATUSES,
    status_display_label,
    status_emoji as domain_status_emoji,
)
from utils.dates import extract_date_component
from utils.timefmt import format_utc_display

# Re-export for existing bot call sites
__all__ = [
    "DEFAULT_STATUS",
    "STATUSES",
    "STATUS_EMOJI",
    "STATUS_LABELS",
    "WORKING_STATUSES",
    "status_label",
    "shipment_title",
    "format_active_list",
    "format_details",
    "format_reminder_notice",
]

STATUS_EMOJI: dict[str, str] = dict(DOMAIN_STATUS_EMOJI)
SELECTOR_STATUS_EMOJI: dict[str, str] = dict(DOMAIN_STATUS_EMOJI)

STATUS_LABELS: dict[str, str] = {
    "standby": f"{DOMAIN_STATUS_EMOJI['standby']} Standby",
    "preparing": f"{DOMAIN_STATUS_EMOJI['preparing']} Preparing",
    "make_label": f"{DOMAIN_STATUS_EMOJI['make_label']} Make Label",
    "enroute": f"{DOMAIN_STATUS_EMOJI['enroute']} En Route",
    "out_for_delivery": f"{DOMAIN_STATUS_EMOJI['out_for_delivery']} Out For Delivery",
    "delivered": f"{DOMAIN_STATUS_EMOJI['delivered']} Delivered",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status_display_label(status))


def status_emoji(status: str) -> str:
    return domain_status_emoji(status)


def selector_status_emoji(status: str) -> str:
    return domain_status_emoji(status)


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


def format_edd_display(shipment: dict[str, Any]) -> str:
    raw = shipment_edd_raw(shipment)
    date_only = extract_date_component(raw)
    if date_only:
        return date_only
    return format_utc_display(raw)


def format_shipment_line(shipment: dict[str, Any]) -> str:
    """One summary line: • DE : Oner ✈️ — 2026-08-09."""
    title = esc(shipment_title(shipment))
    emoji = status_emoji(shipment.get("status", ""))
    edd = format_edd_display(shipment)

    if emoji:
        line = f"• {title} {emoji}"
    else:
        line = f"• {title}"

    if edd and edd != "—":
        line = f"{line} — {esc(edd)}"
    return line


def format_active_list(shipments: list[dict[str, Any]]) -> str:
    """Main summary: In Transit first, then Working On."""
    if not shipments:
        return (
            "📦 <b>Shipments</b>\n\n"
            "No active shipments yet.\n"
            "Tap ➕ Add to create one."
        )

    in_transit: list[dict[str, Any]] = []
    working: list[dict[str, Any]] = []
    for item in shipments:
        status = item.get("status")
        if status in IN_TRANSIT_STATUSES:
            in_transit.append(item)
        elif status in WORKING_STATUSES:
            working.append(item)

    working.sort(
        key=lambda item: (
            WORKING_STATUSES.index(item["status"])
            if item.get("status") in WORKING_STATUSES
            else 99,
            item.get("id") or 0,
        )
    )
    in_transit.sort(
        key=lambda item: (
            IN_TRANSIT_STATUSES.index(item["status"])
            if item.get("status") in IN_TRANSIT_STATUSES
            else 99,
            item.get("id") or 0,
        )
    )

    parts = ["📦 <b>Shipments</b>"]
    if in_transit:
        parts.append("")
        parts.append("<b>In Transit:</b>")
        for item in in_transit:
            parts.append(format_shipment_line(item))
    if working:
        parts.append("")
        parts.append("<b>Working On:</b>")
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
    edd = format_edd_display(shipment)
    updated = shipment.get("updated_at") or "—"
    reminder = reminder_text or "—"
    return (
        "<b>📦 Shipment</b>\n\n"
        f"ID: #{shipment.get('id', '—')}\n"
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
    edd = format_edd_display(shipment)
    return (
        "⏰ <b>Shipment Reminder</b>\n\n"
        f"{esc(shipment_title(shipment))}\n"
        f"Status: {status_label(shipment['status'])}\n"
        f"Expected delivery: {esc(edd)}"
    )


def format_reminder_menu(shipment: dict[str, Any], reminder_text: str | None) -> str:
    edd = format_edd_display(shipment)
    current = reminder_text or "—"
    return (
        "⏰ <b>Shipment Reminder</b>\n\n"
        f"{esc(shipment_title(shipment))}\n"
        f"EDD: {esc(edd)}\n"
        f"Reminder: {esc(current)}"
    )
