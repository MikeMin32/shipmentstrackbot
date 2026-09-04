"""Editable new-shipment draft stored in FSM memory."""

from __future__ import annotations

from typing import Any

from domain.status import DEFAULT_STATUS

DEFAULT_DRAFT: dict[str, Any] = {
    "name": None,
    "country": None,
    "account_id": None,
    "client_team_id": None,
    "box_weight": None,
    "status": DEFAULT_STATUS,
    "label_creation_date": None,
    "scanned_in_date": None,
    "expected_delivery_date": None,
    "note": None,
}

REQUIRED_FIELDS = ("name", "country", "account_id")


def new_draft() -> dict[str, Any]:
    return dict(DEFAULT_DRAFT)


def draft_missing(draft: dict[str, Any] | None) -> list[str]:
    data = draft or {}
    missing: list[str] = []
    if not str(data.get("name") or "").strip():
        missing.append("name")
    if not str(data.get("country") or "").strip():
        missing.append("country")
    if not data.get("account_id"):
        missing.append("account")
    return missing
