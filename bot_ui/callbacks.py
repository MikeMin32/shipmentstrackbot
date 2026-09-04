"""Compact CallbackData factories for the workspace UI."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class NavCB(CallbackData, prefix="n"):
    """Home, lists, search, accounts, archive, back, noop."""

    x: str
    p: int = 0
    i: int = 0
    f: str = ""


class ShipCB(CallbackData, prefix="s"):
    """Shipment details and shipment-scoped actions."""

    x: str
    i: int
    p: int = 0


class PickCB(CallbackData, prefix="p"):
    """Reusable dropdown-like picker."""

    x: str
    k: str
    t: str
    i: int = 0
    p: int = 0
    n: int = 0


class DateCB(CallbackData, prefix="d"):
    """Date shortcuts and inline calendar."""

    x: str
    f: str
    t: str
    i: int = 0
    y: int = 0
    m: int = 0
    n: int = 0


class RemCB(CallbackData, prefix="r"):
    """Reminder presets, date, and time."""

    x: str
    i: int
    n: int = 0
    y: int = 0
    m: int = 0
    d: int = 0


class OpenCB(CallbackData, prefix="o"):
    """Open shipment from a reminder notification (may adopt the message)."""

    i: int
