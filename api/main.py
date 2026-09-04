"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers import accounts, dashboard, lookups, shipments, teams
from config import Config, load_config
from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository

logger = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(cfg.database_path)
        await db.connect()
        shipments_repo = ShipmentRepository(db)
        migrated = await shipments_repo.migrate_legacy_statuses()
        if migrated:
            logger.info("Migrated %s legacy status value(s) to standby", migrated)
        app.state.config = cfg
        app.state.db = db
        app.state.shipments = shipments_repo
        app.state.accounts = AccountRepository(db)
        app.state.teams = ClientTeamRepository(db)
        logger.info(
            "API ready environment=%s dev_auth=%s timezone=%s",
            cfg.environment,
            cfg.dev_auth_enabled,
            cfg.app_timezone,
        )
        try:
            yield
        finally:
            await db.close()

    app = FastAPI(
        title="Shipment Tracker API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None if cfg.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if cfg.is_production else "/api/openapi.json",
    )
    app.state.config = cfg

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, StarletteHTTPException):
            return await http_exception_handler(request, exc)
        if isinstance(exc, RequestValidationError):
            return await request_validation_exception_handler(request, exc)
        logger.exception("Unhandled API error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(dashboard.router)
    app.include_router(shipments.router)
    app.include_router(accounts.router)
    app.include_router(teams.router)
    app.include_router(lookups.router)

    dist = cfg.frontend_dist
    if dist is not None and dist.is_dir() and (dist / "index.html").is_file():
        _mount_frontend(app, dist)
        logger.info("Serving Mini App static files from %s", dist)

    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
