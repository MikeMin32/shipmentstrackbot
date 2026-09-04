"""FastAPI dependencies."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from api.auth import InitDataError, TelegramUser, extract_init_data, validate_init_data
from config import Config
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository

logger = logging.getLogger(__name__)


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_shipments(request: Request) -> ShipmentRepository:
    return request.app.state.shipments


def get_accounts(request: Request) -> AccountRepository:
    return request.app.state.accounts


def get_teams(request: Request) -> ClientTeamRepository:
    return request.app.state.teams


async def require_telegram_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_telegram_init_data: Annotated[str | None, Header(alias="X-Telegram-Init-Data")] = None,
) -> TelegramUser:
    config: Config = request.app.state.config
    init_data = extract_init_data(authorization, x_telegram_init_data)

    if init_data:
        try:
            user = validate_init_data(
                init_data,
                config.bot_token,
                max_age_seconds=config.init_data_max_age_seconds,
            )
        except InitDataError as exc:
            logger.warning("Telegram Mini App auth rejected: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        if user.id not in config.allowed_user_ids:
            logger.warning("Allowlist rejected Telegram user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        return user

    if config.dev_auth_enabled and config.dev_telegram_user_id is not None:
        return TelegramUser(
            id=config.dev_telegram_user_id,
            first_name="Dev",
            username="dev",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Open this app from Telegram",
    )


ConfigDep = Annotated[Config, Depends(get_config)]
ShipmentsDep = Annotated[ShipmentRepository, Depends(get_shipments)]
AccountsDep = Annotated[AccountRepository, Depends(get_accounts)]
TeamsDep = Annotated[ClientTeamRepository, Depends(get_teams)]
UserDep = Annotated[TelegramUser, Depends(require_telegram_user)]
