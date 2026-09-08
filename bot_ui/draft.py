"""Editable new-shipment draft stored in FSM memory."""

from __future__ import annotations

from typing import Any

from domain.status import DEFAULT_STATUS

DEFAULT_DRAFT: dict[str, Any] = {
    "account_id": None,
    "name": None,
    "country": None,
    "client_team_id": None,
    "unit_quantity": None,
    "status": DEFAULT_STATUS,
    "label_creation_date": None,
    "scanned_in_date": None,
    "expected_delivery_date": None,
    "note": None,
}

REQUIRED_FIELDS = ("account_id", "name", "country")


def new_draft() -> dict[str, Any]:
    return dict(DEFAULT_DRAFT)


def prefill_from_account(draft: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    """Default Name and Country from the selected account. Both stay editable."""
    account_id = account.get("id")
    draft["account_id"] = int(account_id) if account_id is not None else None
    name = str(account.get("name") or "").strip()
    draft["name"] = name or None
    country = str(account.get("country") or "").strip()
    draft["country"] = country or None
    return draft


def draft_missing(draft: dict[str, Any] | None) -> list[str]:
    data = draft or {}
    missing: list[str] = []
    if not data.get("account_id"):
        missing.append("account")
    if not str(data.get("name") or "").strip():
        missing.append("name")
    if not str(data.get("country") or "").strip():
        missing.append("country")
    return missing
