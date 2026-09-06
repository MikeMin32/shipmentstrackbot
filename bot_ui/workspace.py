"""Present and keep a single workspace message per authorized user."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot_ui.views import View
from database.entities import AccountRepository
from database.repository import ShipmentRepository
from database.sessions import BotSessionRepository

logger = logging.getLogger(__name__)

OUTDATED_ALERT = "This panel is outdated. Open the current menu."


def is_outdated_workspace(
    session: dict[str, Any] | None,
    message: Message | None,
) -> bool:
    if session is None or message is None:
        return False
    return int(session["message_id"]) != int(message.message_id)


def workspace_needs_reposition(session: dict[str, Any] | None) -> bool:
    """True when notices were sent after the stored workspace message."""
    if session is None:
        return False
    return bool(int(session.get("needs_reposition") or 0))


async def try_delete_message(message: Message | None) -> bool:
    if message is None:
        return False
    try:
        await message.delete()
        return True
    except TelegramBadRequest:
        return False
    except Exception:
        logger.debug("Could not delete message", exc_info=True)
        return False


async def strip_keyboard(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        return
    except Exception:
        logger.debug("Could not strip workspace keyboard", exc_info=True)


async def retire_workspace(bot: Bot, chat_id: int, message_id: int) -> None:
    """Remove the old workspace message, falling back to stripping its keyboard."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return
    except TelegramBadRequest:
        pass
    except Exception:
        logger.debug("Could not delete workspace message", exc_info=True)
    await strip_keyboard(bot, chat_id, message_id)


async def _record_workspace(
    sessions: BotSessionRepository,
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    view_name: str,
) -> None:
    await sessions.upsert(
        telegram_user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        current_view=view_name,
        needs_reposition=0,
    )


async def ensure_workspace_at_bottom(
    bot: Bot,
    sessions: BotSessionRepository,
    *,
    user_id: int,
    chat_id: int,
    view: View,
    session: dict[str, Any] | None,
) -> int:
    """Retire the buried workspace and send the requested view as a new message."""
    if session is not None:
        await retire_workspace(
            bot,
            int(session["chat_id"]),
            int(session["message_id"]),
        )
    sent = await bot.send_message(chat_id, view.text, reply_markup=view.markup)
    await _record_workspace(
        sessions,
        user_id=user_id,
        chat_id=chat_id,
        message_id=sent.message_id,
        view_name=view.name,
    )
    return sent.message_id


async def present(
    bot: Bot,
    sessions: BotSessionRepository,
    *,
    user_id: int,
    chat_id: int,
    view: View,
    prefer_message_id: int | None = None,
    force_new: bool = False,
    from_notice: bool = False,
) -> int:
    """Edit the active workspace or send a new one. Returns the active message_id.

    Reminder/notice messages are never adopted or edited. If a notice was sent
    after the stored workspace, the old panel is retired and the requested view
    is sent as a new message below that history.
    """
    session = await sessions.get(user_id)
    if from_notice:
        # Never treat a reminder/notice as the workspace edit target.
        prefer_message_id = None

    if workspace_needs_reposition(session) and not force_new:
        return await ensure_workspace_at_bottom(
            bot,
            sessions,
            user_id=user_id,
            chat_id=chat_id,
            view=view,
            session=session,
        )

    target_id = prefer_message_id
    if target_id is None and session is not None and not force_new:
        target_id = int(session["message_id"])
        chat_id = int(session["chat_id"])

    if force_new:
        target_id = None

    if target_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=target_id,
                text=view.text,
                reply_markup=view.markup,
            )
            await _record_workspace(
                sessions,
                user_id=user_id,
                chat_id=chat_id,
                message_id=target_id,
                view_name=view.name,
            )
            return target_id
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=target_id,
                        reply_markup=view.markup,
                    )
                except TelegramBadRequest:
                    pass
                await _record_workspace(
                    sessions,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=target_id,
                    view_name=view.name,
                )
                return target_id
            logger.info("Workspace edit failed (%s); sending a new panel", exc)

    if session is not None:
        if workspace_needs_reposition(session):
            await retire_workspace(
                bot, int(session["chat_id"]), int(session["message_id"])
            )
        else:
            await strip_keyboard(bot, int(session["chat_id"]), int(session["message_id"]))

    sent = await bot.send_message(chat_id, view.text, reply_markup=view.markup)
    await _record_workspace(
        sessions,
        user_id=user_id,
        chat_id=chat_id,
        message_id=sent.message_id,
        view_name=view.name,
    )
    return sent.message_id


async def present_from_callback(
    callback: CallbackQuery,
    sessions: BotSessionRepository,
    view: View,
    *,
    from_notice: bool = False,
) -> None:
    if callback.message is None or not isinstance(callback.message, Message):
        return
    bot = callback.bot
    user = callback.from_user
    if user is None:
        return
    await present(
        bot,
        sessions,
        user_id=user.id,
        chat_id=callback.message.chat.id,
        view=view,
        prefer_message_id=None if from_notice else callback.message.message_id,
        from_notice=from_notice,
    )


async def refresh_other_homes(
    bot: Bot,
    sessions: BotSessionRepository,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    *,
    except_user_id: int,
    tz_name: str,
) -> None:
    from bot_ui.views import view_home

    rows = await sessions.list_by_view("home")
    for row in rows:
        if int(row["telegram_user_id"]) == except_user_id:
            continue
        if workspace_needs_reposition(row):
            continue
        try:
            view = await view_home(repo, accounts, tz_name=tz_name)
            await bot.edit_message_text(
                chat_id=int(row["chat_id"]),
                message_id=int(row["message_id"]),
                text=view.text,
                reply_markup=view.markup,
            )
        except TelegramBadRequest:
            continue
        except Exception:
            logger.debug(
                "Home refresh failed for user %s",
                row.get("telegram_user_id"),
                exc_info=True,
            )
