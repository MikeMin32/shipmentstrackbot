"""Parsing helpers for workspace free-text input."""

from __future__ import annotations

from database.repository import MAX_BOX_WEIGHT, validate_box_weight


def parse_weight_text(raw: str) -> float:
    text = (raw or "").strip().lower().replace("kg", "").replace(" ", "").replace(",", ".")
    if not text:
        raise ValueError("Enter a weight in kg")
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError("Weight must be a number") from exc
    return validate_box_weight(value)


def parse_name(raw: str, *, max_len: int, empty_message: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise ValueError(empty_message)
    if cleaned.startswith("/"):
        raise ValueError(empty_message)
    if len(cleaned) > max_len:
        raise ValueError(f"Too long (max {max_len})")
    return cleaned


MAX_WEIGHT = MAX_BOX_WEIGHT
