"""Parsing helpers for workspace free-text input."""

from __future__ import annotations

from database.repository import MAX_UNIT_QUANTITY, validate_unit_quantity


def parse_unit_quantity_text(raw: str) -> float:
    text = (raw or "").strip().lower().replace(",", ".")
    if text.endswith("kg"):
        text = text[:-2]
    if text.endswith("u"):
        text = text[:-1]
    text = text.replace(" ", "")
    if not text:
        raise ValueError("Enter a unit quantity")
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError("Unit quantity must be a number") from exc
    return validate_unit_quantity(value)


def parse_name(raw: str, *, max_len: int, empty_message: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise ValueError(empty_message)
    if cleaned.startswith("/"):
        raise ValueError(empty_message)
    if len(cleaned) > max_len:
        raise ValueError(f"Too long (max {max_len})")
    return cleaned
