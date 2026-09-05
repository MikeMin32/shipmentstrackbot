from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_bot_modules_import_without_fastapi() -> None:
    import bot
    from handlers import get_root_router
    from services.reminder_worker import ReminderWorker
    from bot_ui.calendar import shift_month
    from bot_ui.workspace import is_outdated_workspace

    assert bot.main is not None
    assert ReminderWorker is not None
    assert get_root_router is not None
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert is_outdated_workspace is not None

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("api")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("run_api")


def test_bot_source_does_not_import_fastapi() -> None:
    root = Path(__file__).resolve().parents[1]
    banned = ("fastapi", "uvicorn", "WebAppInfo", "MenuButtonWebApp", "MINI_APP_URL")
    scanned = [
        root / "bot.py",
        root / "config.py",
        root / "handlers",
        root / "bot_ui",
        root / "services",
        root / "keyboards",
        root / "middlewares",
        root / "database",
        root / "domain",
    ]
    hits: list[str] = []
    for target in scanned:
        paths = [target] if target.is_file() else sorted(target.glob("**/*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for needle in banned:
                if needle in text:
                    hits.append(f"{path.relative_to(root)}: {needle}")
    assert hits == []
