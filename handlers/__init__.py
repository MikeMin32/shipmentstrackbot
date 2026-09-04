"""Handler routers."""

from aiogram import Router

from config import Config
from handlers.workspace import router as workspace_router


def get_root_router(config: Config) -> Router:
    del config
    root = Router()
    # /start and /menu are workspace-only. Do not register handlers.start.
    root.include_router(workspace_router)
    return root
