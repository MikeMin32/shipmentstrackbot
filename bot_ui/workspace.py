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


async def present(
    bot: Bot,
    sessions: BotSessionRepository,
    *,
    user_id: int,
    chat_id: int,
    view: View,
    prefer_message_id: int | None = None,
    adopt_message: Message | None = None,
    force_new: bool = False,
) -> int:
    """Edit the active workspace or send a new one. Returns the active message_id."""
    session = await sessions.get(user_id)
    target_id = prefer_message_id
    if target_id is None and session is not None and not force_new:
        target_id = int(session["message_id"])
        chat_id = int(session["chat_id"])

    if adopt_message is not None:
        target_id = adopt_message.message_id
        chat_id = adopt_message.chat.id
        if session is not None and int(session["message_id"]) != target_id:
            await strip_keyboard(bot, int(session["chat_id"]), int(session["message_id"]))

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
            await sessions.upsert(
                telegram_user_id=user_id,
                chat_id=chat_id,
                message_id=target_id,
                current_view=view.name,
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
                await sessions.upsert(
                    telegram_user_id=user_id,
                    chat_id=chat_id,
                    message_id=target_id,
                    current_view=view.name,
                )
                return target_id
            logger.info("Workspace edit failed (%s); sending a new panel", exc)

    if session is not None:
        await strip_keyboard(bot, int(session["chat_id"]), int(session["message_id"]))

    sent = await bot.send_message(chat_id, view.text, reply_markup=view.markup)
    await sessions.upsert(
        telegram_user_id=user_id,
        chat_id=chat_id,
        message_id=sent.message_id,
        current_view=view.name,
    )
    return sent.message_id


async def present_from_callback(
    callback: CallbackQuery,
    sessions: BotSessionRepository,
    view: View,
    *,
    adopt: bool = False,
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
        prefer_message_id=None if adopt else callback.message.message_id,
        adopt_message=callback.message if adopt else None,
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
