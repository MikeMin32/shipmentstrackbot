"""Shared handler helpers."""

from __future__ import annotations

from database.repository import ShipmentRepository
from utils.formatting import format_details
from utils.timefmt import format_utc_display


async def details_text(
    repo: ShipmentRepository,
    shipment: dict,
    *,
    notice: str | None = None,
) -> str:
    reminder = await repo.get_active_reminder(shipment["id"])
    reminder_text = None
    if reminder:
        reminder_text = format_utc_display(reminder["remind_at"])
    text = format_details(shipment, reminder_text=reminder_text)
    if notice:
        return f"{notice}\n\n{text}"
    return text
