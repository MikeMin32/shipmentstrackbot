"""Client team endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.deps import TeamsDep, UserDep
from api.schemas import NamedEntityCreate, NamedEntityUpdate
from services.serialize import serialize_team

router = APIRouter(prefix="/api/client-teams", tags=["client-teams"])


@router.get("")
async def list_teams(user: UserDep, teams: TeamsDep) -> list[dict]:
    del user
    return [serialize_team(row) for row in await teams.list_all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: NamedEntityCreate,
    user: UserDep,
    teams: TeamsDep,
) -> dict:
    del user
    try:
        row = await teams.create(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_team(row)


@router.patch("/{team_id}")
async def rename_team(
    team_id: int,
    payload: NamedEntityUpdate,
    user: UserDep,
    teams: TeamsDep,
) -> dict:
    del user
    try:
        row = await teams.rename(team_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Client team not found")
    return serialize_team(row)
