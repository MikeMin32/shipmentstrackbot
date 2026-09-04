from __future__ import annotations


def test_bot_modules_import() -> None:
    import bot
    import run_api
    from handlers import get_root_router
    from services.reminder_worker import ReminderWorker
    from bot_ui.calendar import shift_month
    from bot_ui.workspace import is_outdated_workspace

    assert bot.main is not None
    assert run_api.main is not None
    assert ReminderWorker is not None
    assert get_root_router is not None
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert is_outdated_workspace is not None
