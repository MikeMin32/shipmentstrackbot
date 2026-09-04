"""Shipment CRUD, status, archive, history, and reminders."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, status

from api.deps import ConfigDep, ShipmentsDep, UserDep
from api.schemas import ReminderUpsert, ShipmentCreate, ShipmentUpdate, StatusUpdate
from domain.status import DEFAULT_STATUS, DELIVERED_STATUS, STATUSES
from services.serialize import (
    serialize_history,
    serialize_reminder,
    serialize_shipment,
)
from utils.dates import today_in_timezone
from utils.timefmt import try_parse_stored

router = APIRouter(prefix="/api/shipments", tags=["shipments"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Shipment not found")


def _unavailable() -> HTTPException:
    return HTTPException(status_code=409, detail="Shipment is archived")


@router.get("")
async def list_shipments(
    user: UserDep,
    shipments: ShipmentsDep,
    q: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    account_id: int | None = None,
    unassigned: bool = False,
    client_team_id: int | None = None,
    archived: bool | None = False,
    active_only: bool = False,
    completed_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    del user
    items, total = await shipments.list_filtered(
        query=q,
        status=status_filter,
        account_id=account_id,
        unassigned_account=unassigned,
        client_team_id=client_team_id,
        archived=archived,
        active_only=active_only,
        completed_only=completed_only,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [serialize_shipment(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentCreate,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    status_value = payload.status or DEFAULT_STATUS
    if status_value not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    row = await shipments.create(
        country=payload.country,
        clone_name=payload.clone,
        status=status_value,
        created_by=user.id,
        note=payload.note,
        expected_delivery_date=payload.expected_delivery_date,
        account_id=payload.account_id,
        client_team_id=payload.client_team_id,
        box_weight=payload.box_weight,
        label_creation_date=payload.label_creation_date,
        scanned_in_date=payload.scanned_in_date,
        require_account=True,
    )
    return serialize_shipment(row)


@router.get("/{shipment_id}")
async def get_shipment(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    del user
    row = await shipments.get_by_id(shipment_id)
    if row is None:
        raise _not_found()
    reminder = await shipments.get_active_reminder(shipment_id)
    payload = serialize_shipment(row)
    payload["reminder"] = serialize_reminder(reminder)
    return payload


@router.patch("/{shipment_id}")
async def update_shipment(
    shipment_id: int,
    payload: ShipmentUpdate,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    del user
    kwargs: dict = {}
    if payload.country is not None:
        kwargs["country"] = payload.country
    if payload.clone is not None:
        kwargs["clone_name"] = payload.clone
    if payload.account_id is not None:
        kwargs["account_id"] = payload.account_id
    if payload.clear_client_team:
        kwargs["client_team_id"] = None
    elif payload.client_team_id is not None:
        kwargs["client_team_id"] = payload.client_team_id
    if payload.clear_box_weight:
        kwargs["box_weight"] = None
    elif payload.box_weight is not None:
        kwargs["box_weight"] = payload.box_weight
    if payload.clear_note:
        kwargs["note"] = None
    elif payload.note is not None:
        kwargs["note"] = payload.note
    if payload.clear_label_creation_date:
        kwargs["label_creation_date"] = None
    elif payload.label_creation_date is not None:
        kwargs["label_creation_date"] = payload.label_creation_date
    if payload.clear_scanned_in_date:
        kwargs["scanned_in_date"] = None
    elif payload.scanned_in_date is not None:
        kwargs["scanned_in_date"] = payload.scanned_in_date
    if payload.clear_expected_delivery_date:
        kwargs["expected_delivery_date"] = None
    elif payload.expected_delivery_date is not None:
        kwargs["expected_delivery_date"] = payload.expected_delivery_date

    row = await shipments.update_fields(shipment_id, **kwargs)
    if row is None:
        existing = await shipments.get_by_id(shipment_id)
        if existing is None:
            raise _not_found()
        raise _unavailable()
    return serialize_shipment(row)


@router.post("/{shipment_id}/status")
async def change_status(
    shipment_id: int,
    payload: StatusUpdate,
    user: UserDep,
    shipments: ShipmentsDep,
    config: ConfigDep,
) -> dict:
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    delivered_date = None
    if payload.status == DELIVERED_STATUS:
        delivered_date = today_in_timezone(config.app_timezone).isoformat()
    row = await shipments.update_status(
        shipment_id,
        payload.status,
        changed_by=user.id,
        delivered_date=delivered_date,
    )
    if row is None:
        existing = await shipments.get_by_id(shipment_id)
        if existing is None:
            raise _not_found()
        raise _unavailable()
    return serialize_shipment(row)


@router.post("/{shipment_id}/complete")
async def complete_shipment(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
    config: ConfigDep,
) -> dict:
    delivered_date = today_in_timezone(config.app_timezone).isoformat()
    row = await shipments.complete(
        shipment_id,
        changed_by=user.id,
        delivered_date=delivered_date,
    )
    if row is None:
        existing = await shipments.get_by_id(shipment_id)
        if existing is None:
            raise _not_found()
        raise _unavailable()
    return serialize_shipment(row)


@router.post("/{shipment_id}/archive")
async def archive_shipment(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    row = await shipments.archive(shipment_id, changed_by=user.id)
    if row is None:
        raise _not_found()
    return serialize_shipment(row)


@router.post("/{shipment_id}/restore")
async def restore_shipment(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    row = await shipments.restore(shipment_id, changed_by=user.id)
    if row is None:
        raise _not_found()
    return serialize_shipment(row)


@router.get("/{shipment_id}/history")
async def shipment_history(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
) -> list[dict]:
    del user
    existing = await shipments.get_by_id(shipment_id)
    if existing is None:
        raise _not_found()
    rows = await shipments.list_history(shipment_id)
    return [serialize_history(row) for row in rows]


@router.get("/{shipment_id}/reminder")
async def get_reminder(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    del user
    existing = await shipments.get_by_id(shipment_id)
    if existing is None:
        raise _not_found()
    reminder = await shipments.get_active_reminder(shipment_id)
    return {"reminder": serialize_reminder(reminder)}


@router.put("/{shipment_id}/reminder")
async def set_reminder(
    shipment_id: int,
    payload: ReminderUpsert,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    remind_at = try_parse_stored(payload.remind_at)
    if remind_at is None:
        raise HTTPException(
            status_code=400,
            detail="remind_at must be an ISO 8601 datetime",
        )
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    try:
        reminder = await shipments.set_reminder(
            shipment_id,
            remind_at,
            created_by=user.id,
        )
    except ValueError as exc:
        existing = await shipments.get_by_id(shipment_id)
        if existing is None:
            raise _not_found() from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_reminder(reminder) or {}


@router.delete("/{shipment_id}/reminder")
async def delete_reminder(
    shipment_id: int,
    user: UserDep,
    shipments: ShipmentsDep,
) -> dict:
    del user
    existing = await shipments.get_by_id(shipment_id)
    if existing is None:
        raise _not_found()
    await shipments.cancel_active_reminders(shipment_id)
    await shipments.db.connection.commit()
    return {"ok": True}
