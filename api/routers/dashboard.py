"""Dashboard and current-user endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import AccountsDep, ConfigDep, ShipmentsDep, UserDep
from api.schemas import TelegramUserOut
from domain.status import IN_TRANSIT_STATUSES, WORKING_STATUSES
from services.serialize import serialize_account, serialize_shipment

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/me")
async def me(user: UserDep, config: ConfigDep) -> dict:
    return {
        "user": TelegramUserOut(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        ).model_dump(),
        "timezone": config.app_timezone,
        "dev_auth": config.dev_auth_enabled,
    }


@router.get("/dashboard")
async def dashboard(
    user: UserDep,
    shipments: ShipmentsDep,
    accounts: AccountsDep,
) -> dict:
    del user
    counts = await shipments.dashboard_counts()
    account_summary = [serialize_account(row) for row in await accounts.summary()]
    active = await shipments.list_active()
    in_transit = [
        serialize_shipment(item)
        for item in active
        if item.get("status") in IN_TRANSIT_STATUSES
    ]
    working = [
        serialize_shipment(item)
        for item in active
        if item.get("status") in WORKING_STATUSES
    ]
    return {
        "counts": counts,
        "accounts": account_summary,
        "active": {
            "in_transit": in_transit,
            "working": working,
        },
    }
