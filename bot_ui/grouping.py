"""Home grouping and EDD-first ordering for active shipments."""

from __future__ import annotations

from typing import Any

from domain.status import HOME_STATUS_ORDER
from utils.dates import extract_date_component


def sort_by_edd(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soonest EDD first, undated after dated, stable id as tie-breaker."""

    def key(item: dict[str, Any]) -> tuple[int, str, int]:
        raw = item.get("expected_delivery_date") or item.get("expected_date")
        iso = extract_date_component(raw)
        shipment_id = int(item.get("id") or 0)
        if iso:
            return (0, iso, shipment_id)
        return (1, "", shipment_id)

    return sorted(shipments, key=key)


def group_home_shipments(
    shipments: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group active shipments into Home status sections. Empty sections are omitted."""
    buckets: dict[str, list[dict[str, Any]]] = {status: [] for status in HOME_STATUS_ORDER}
    for item in shipments:
        status = item.get("status")
        if status in buckets:
            buckets[status].append(item)
    return [
        (status, sort_by_edd(buckets[status]))
        for status in HOME_STATUS_ORDER
        if buckets[status]
    ]


def group_active_shipments(
    shipments: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Compatibility alias for Home status grouping."""
    return group_home_shipments(shipments)


def ordered_active_shipments(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for _status, items in group_home_shipments(shipments):
        ordered.extend(items)
    return ordered


def page_active_shipments(
    shipments: list[dict[str, Any]],
    page: int,
    *,
    size: int = 9,
) -> tuple[list[dict[str, Any]], int, int, int]:
    ordered = ordered_active_shipments(shipments)
    total = len(ordered)
    pages = max(1, (total + size - 1) // size) if total else 1
    page = max(0, min(page, pages - 1))
    start = page * size
    return ordered[start : start + size], page, pages, total


def home_priority_shipments(
    shipments: list[dict[str, Any]],
    *,
    limit: int = 9,
) -> list[dict[str, Any]]:
    return ordered_active_shipments(shipments)[:limit]


def standby_account_row(account: dict[str, Any]) -> dict[str, Any]:
    """Home STANDBY placeholder for an idle active account (not a new shipment)."""
    name = str(account.get("name") or "Account")
    country = (account.get("country") or "").strip() or None
    return {
        "id": 0,
        "status": "standby",
        "account_id": account.get("id"),
        "account_name": name,
        "name": name,
        "country": country,
        "home_kind": "account",
        "expected_delivery_date": None,
        "archived": 0,
    }
