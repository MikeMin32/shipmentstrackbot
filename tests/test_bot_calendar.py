from __future__ import annotations

from datetime import date

from bot_ui.calendar import month_title, month_weeks, shift_month


def test_shift_month_december_to_january() -> None:
    assert shift_month(2026, 12, 1) == (2027, 1)


def test_shift_month_january_to_december() -> None:
    assert shift_month(2026, 1, -1) == (2025, 12)


def test_shift_month_multi_year() -> None:
    assert shift_month(2024, 3, 24) == (2026, 3)
    assert shift_month(2026, 3, -24) == (2024, 3)


def test_february_leap_year() -> None:
    days = [day.day for week in month_weeks(2024, 2) for day in week if day]
    assert 29 in days
    assert 30 not in days
    assert days[0] == 1
    assert days[-1] == 29


def test_february_non_leap_year() -> None:
    days = [day.day for week in month_weeks(2025, 2) for day in week if day]
    assert 28 in days
    assert 29 not in days
    assert days[-1] == 28


def test_month_weeks_monday_first() -> None:
    weeks = month_weeks(2026, 9)
    first = next(day for day in weeks[0] if day is not None)
    assert first == date(2026, 9, 1)
    assert first.weekday() == 1  # Tuesday
    assert weeks[0][0] is None  # Monday empty
    assert weeks[0][1] == date(2026, 9, 1)


def test_month_title_is_english() -> None:
    assert month_title(2026, 9) == "September 2026"
    assert month_title(2024, 2) == "February 2024"
