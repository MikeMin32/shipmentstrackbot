"""Inline calendar date math (Monday-first weeks)."""

from __future__ import annotations

from calendar import Calendar
from datetime import date

WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_CAL = Calendar(firstweekday=0)


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift a year/month by ``delta`` months, wrapping across year boundaries."""
    if month < 1 or month > 12:
        raise ValueError("month must be 1-12")
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def month_weeks(year: int, month: int) -> list[list[date | None]]:
    """Return Monday-first weeks for a month. Leading/trailing cells are None."""
    weeks: list[list[date | None]] = []
    for week in _CAL.monthdayscalendar(year, month):
        weeks.append([date(year, month, day) if day else None for day in week])
    return weeks


def month_title(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"
