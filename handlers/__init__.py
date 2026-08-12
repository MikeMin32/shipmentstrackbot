"""Handler routers."""

from aiogram import Router

from handlers.callbacks import router as callbacks_router
from handlers.shipments import router as shipments_router
from handlers.start import router as start_router


def get_root_router() -> Router:
    root = Router()
    root.include_router(start_router)
    root.include_router(callbacks_router)
    root.include_router(shipments_router)
    return root
