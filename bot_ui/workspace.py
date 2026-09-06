"""Present and keep a single workspace message per authorized user."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramConflictError,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot_ui.views import View
from database.entities import AccountRepository
from database.repository import ShipmentRepository
from database.sessions import BotSessionRepository

logger = logging.getLogger(__name__)

OUTDATED_ALERT = "This panel is outdated. Open the current menu."

_STALE_MESSAGE_MARKERS = (
    "message to edit not found",
    "message to delete not found",
    "message can't be edited",
    "message can't be deleted",
    "message identifier is invalid",
    "message_id_invalid",
    "message not found",
)

_SERIOUS_TELEGRAM_ERRORS = (
    TelegramUnauthorizedError,
    TelegramForbiddenError,
    TelegramConflictError,
    TelegramRetryAfter,
    TelegramServerError,
)


def is_outdated_workspace(
    session: dict[str, Any] | None,
    message: Message | InaccessibleMessage | None,
) -> bool:
    if session is None or message is None:
        return False
    message_id = getattr(message, "message_id", None)
    if message_id is None:
        return False
    return int(session["message_id"]) != int(message_id)


def workspace_needs_reposition(session: dict[str, Any] | None) -> bool:
    """True when notices were sent after the stored workspace message."""
    if session is None:
        return False
    return bool(int(session.get("needs_reposition") or 0))


def is_unmodified_message_error(exc: BaseException) -> bool:
    return "message is not modified" in str(exc).lower()


def is_stale_workspace_error(exc: BaseException) -> bool:
    """True when Telegram no longer has an editable workspace message."""
    if isinstance(exc, TelegramNotFound):
        return True
    if isinstance(exc, _SERIOUS_TELEGRAM_ERRORS):
        return False
    if not isinstance(exc, TelegramAPIError):
        return False
    if is_unmodified_message_error(exc):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in _STALE_MESSAGE_MARKERS)


def _callback_chat_id(callback: CallbackQuery, session: dict[str, Any] | None) -> int | None:
    message = callback.message
    if message is not None and getattr(message, "chat", None) is not None:
        return int(message.chat.id)
    if session is not None:
        return int(session["chat_id"])
    user = callback.from_user
    if user is not None:
        return int(user.id)
    return None


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
    except TelegramAPIError:
        return
    except Exception:
        logger.debug("Could not strip workspace keyboard", exc_info=True)


async def retire_workspace(bot: Bot, chat_id: int, message_id: int) -> None:
    """Remove the old workspace message, falling back to stripping its keyboard."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return
    except TelegramAPIError:
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


async def _send_new_workspace(
    bot: Bot,
    sessions: BotSessionRepository,
    *,
    user_id: int,
    chat_id: int,
    view: View,
) -> int:
    sent = await bot.send_message(chat_id, view.text, reply_markup=view.markup)
    await _record_workspace(
        sessions,
        user_id=user_id,
        chat_id=chat_id,
        message_id=sent.message_id,
        view_name=view.name,
    )
    return sent.message_id


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
    return await _send_new_workspace(
        bot,
        sessions,
        user_id=user_id,
        chat_id=chat_id,
        view=view,
    )


async def present(
    bot: Bot,
    sessions: BotSessionRepository,
    *,
    user_id: int,
    chat_id: int,
    view: View,
    prefer_message_id: int | None = None,
    from_notice: bool = False,
) -> int:
    """Show a view in the single active workspace. Returns the active message_id.

    A stored message ID is never assumed to still exist. If that Telegram
    message is gone or uneditable, the requested view is sent as a new
    workspace and the session is updated.
    """
    session = await sessions.get(user_id)
    if from_notice:
        prefer_message_id = None

    if workspace_needs_reposition(session):
        return await ensure_workspace_at_bottom(
            bot,
            sessions,
            user_id=user_id,
            chat_id=chat_id,
            view=view,
            session=session,
        )

    if session is None:
        return await _send_new_workspace(
            bot,
            sessions,
            user_id=user_id,
            chat_id=chat_id,
            view=view,
        )

    target_id = prefer_message_id
    edit_chat_id = chat_id
    if target_id is None:
        target_id = int(session["message_id"])
        edit_chat_id = int(session["chat_id"])

    try:
        await bot.edit_message_text(
            chat_id=edit_chat_id,
            message_id=target_id,
            text=view.text,
            reply_markup=view.markup,
        )
        await _record_workspace(
            sessions,
            user_id=user_id,
            chat_id=edit_chat_id,
            message_id=target_id,
            view_name=view.name,
        )
        return target_id
    except TelegramAPIError as exc:
        if is_unmodified_message_error(exc):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=edit_chat_id,
                    message_id=target_id,
                    reply_markup=view.markup,
                )
            except TelegramAPIError as markup_exc:
                if is_stale_workspace_error(markup_exc):
                    logger.info(
                        "Workspace markup edit failed on stale message (%s); "
                        "recovering with a new panel",
                        markup_exc,
                    )
                elif not is_unmodified_message_error(markup_exc):
                    raise
                else:
                    await _record_workspace(
                        sessions,
                        user_id=user_id,
                        chat_id=edit_chat_id,
                        message_id=target_id,
                        view_name=view.name,
                    )
                    return target_id
            else:
                await _record_workspace(
                    sessions,
                    user_id=user_id,
                    chat_id=edit_chat_id,
                    message_id=target_id,
                    view_name=view.name,
                )
                return target_id
        elif is_stale_workspace_error(exc):
            logger.info(
                "Workspace message %s is stale (%s); sending a new panel",
                target_id,
                exc,
            )
        else:
            raise

    await retire_workspace(
        bot, int(session["chat_id"]), int(session["message_id"])
    )
    try:
        return await _send_new_workspace(
            bot,
            sessions,
            user_id=user_id,
            chat_id=chat_id,
            view=view,
        )
    except Exception:
        logger.exception("Failed to send replacement workspace for user %s", user_id)
        raise


async def present_from_callback(
    callback: CallbackQuery,
    sessions: BotSessionRepository,
    view: View,
    *,
    from_notice: bool = False,
) -> None:
    user = callback.from_user
    if user is None:
        return
    session = await sessions.get(user.id)
    chat_id = _callback_chat_id(callback, session)
    if chat_id is None:
        return
    prefer_message_id = None
    message = callback.message
    if isinstance(message, Message) and not from_notice:
        prefer_message_id = message.message_id
    try:
        await present(
            callback.bot,
            sessions,
            user_id=user.id,
            chat_id=chat_id,
            view=view,
            prefer_message_id=prefer_message_id,
            from_notice=from_notice,
        )
    except Exception:
        logger.exception("Workspace presentation failed from callback")


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
        except TelegramAPIError:
            continue
        except Exception:
            logger.debug(
                "Home refresh failed for user %s",
                row.get("telegram_user_id"),
                exc_info=True,
            )
