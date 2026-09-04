"""Home grouping and EDD-first ordering for active shipments."""

from __future__ import annotations

from typing import Any

from domain.status import IN_TRANSIT_STATUSES, WORKING_STATUSES
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


def group_active_shipments(
    shipments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    in_transit = [item for item in shipments if item.get("status") in IN_TRANSIT_STATUSES]
    working = [item for item in shipments if item.get("status") in WORKING_STATUSES]
    return sort_by_edd(in_transit), sort_by_edd(working)


def ordered_active_shipments(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    in_transit, working = group_active_shipments(shipments)
    return in_transit + working


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
