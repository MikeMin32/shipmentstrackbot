"""Lookup endpoints for reusable form values."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import ShipmentsDep, UserDep
from domain.status import (
    ACTIVE_STATUSES,
    COMPLETED_STATUSES,
    DEFAULT_STATUS,
    IN_TRANSIT_STATUSES,
    STATUS_DISPLAY_LABELS,
    STATUSES,
    WORKING_STATUSES,
)

router = APIRouter(prefix="/api", tags=["lookups"])


@router.get("/statuses")
async def list_statuses(user: UserDep) -> dict:
    del user
    return {
        "default": DEFAULT_STATUS,
        "items": [
            {"id": status, "label": STATUS_DISPLAY_LABELS[status]}
            for status in STATUSES
        ],
        "groups": {
            "working": list(WORKING_STATUSES),
            "in_transit": list(IN_TRANSIT_STATUSES),
            "completed": list(COMPLETED_STATUSES),
            "active": list(ACTIVE_STATUSES),
        },
    }


@router.get("/countries")
async def list_countries(user: UserDep, shipments: ShipmentsDep) -> list[str]:
    del user
    return await shipments.distinct_countries()


@router.get("/clones")
async def list_clones(user: UserDep, shipments: ShipmentsDep) -> list[str]:
    del user
    return await shipments.distinct_clones()
