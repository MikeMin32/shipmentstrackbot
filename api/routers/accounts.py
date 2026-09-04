"""Account endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.deps import AccountsDep, UserDep
from api.schemas import NamedEntityCreate, NamedEntityUpdate
from services.serialize import serialize_account

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(user: UserDep, accounts: AccountsDep) -> list[dict]:
    del user
    return [serialize_account(row) for row in await accounts.list_all()]


@router.get("/summary")
async def account_summary(user: UserDep, accounts: AccountsDep) -> list[dict]:
    del user
    return [serialize_account(row) for row in await accounts.summary()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: NamedEntityCreate,
    user: UserDep,
    accounts: AccountsDep,
) -> dict:
    del user
    try:
        row = await accounts.create(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_account(row)


@router.patch("/{account_id}")
async def rename_account(
    account_id: int,
    payload: NamedEntityUpdate,
    user: UserDep,
    accounts: AccountsDep,
) -> dict:
    del user
    try:
        row = await accounts.rename(account_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return serialize_account(row)
