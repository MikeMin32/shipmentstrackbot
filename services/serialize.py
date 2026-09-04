"""Serialize database rows into API-friendly JSON structures."""

from __future__ import annotations

from typing import Any

from domain.status import status_display_label, status_group
from utils.dates import extract_date_component
from utils.timefmt import try_parse_stored


def _entity(entity_id: Any, name: Any) -> dict[str, Any] | None:
    if entity_id is None:
        return None
    return {"id": int(entity_id), "name": name or ""}


def serialize_shipment(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("status") or ""
    return {
        "id": row["id"],
        "country": row.get("country") or "",
        "clone": row.get("clone_name") or "",
        "title": _title(row),
        "status": status,
        "status_label": status_display_label(status),
        "status_group": status_group(status),
        "account": _entity(row.get("account_id"), row.get("account_name")),
        "client_team": _entity(row.get("client_team_id"), row.get("client_team_name")),
        "box_weight": row.get("box_weight"),
        "label_creation_date": extract_date_component(row.get("label_creation_date")),
        "scanned_in_date": extract_date_component(row.get("scanned_in_date")),
        "expected_delivery_date": extract_date_component(row.get("expected_delivery_date")),
        "delivered_date": extract_date_component(row.get("delivered_date")),
        "note": row.get("note"),
        "archived": bool(row.get("archived")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "created_by": row.get("created_by"),
    }


def serialize_account(row: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.get("id"),
        "name": row.get("name") or "No account",
        "archived": bool(row.get("archived")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if "total" in row:
        payload["total"] = int(row["total"] or 0)
        payload["active"] = int(row.get("active") or 0)
    if row.get("unassigned"):
        payload["unassigned"] = True
    return payload


def serialize_team(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "archived": bool(row.get("archived")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_history(row: dict[str, Any]) -> dict[str, Any]:
    old_status = row.get("old_status")
    new_status = row.get("new_status")
    return {
        "id": row["id"],
        "old_status": old_status,
        "old_status_label": status_display_label(old_status) if old_status else None,
        "new_status": new_status,
        "new_status_label": status_display_label(new_status) if new_status else None,
        "changed_by": row.get("changed_by"),
        "changed_at": row.get("changed_at"),
    }


def serialize_reminder(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    remind_at = row.get("remind_at")
    dt = try_parse_stored(remind_at)
    return {
        "id": row["id"],
        "shipment_id": row["shipment_id"],
        "remind_at": dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else remind_at,
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
    }


def _title(row: dict[str, Any]) -> str:
    country = (row.get("country") or "").strip()
    clone = (row.get("clone_name") or "").strip()
    if country and clone:
        return f"{country} : {clone}"
    return clone or country or (row.get("display_name") or f"#{row.get('id', '?')}")
