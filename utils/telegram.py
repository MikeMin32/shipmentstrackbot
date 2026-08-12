"""Telegram message helpers."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def safe_edit_text(
    message: Message | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if message is None or not isinstance(message, Message):
        logger.warning("Cannot edit: message is missing or inaccessible")
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        # Fallback if message cannot be edited (too old, etc.)
        logger.warning("Failed to edit message (%s); sending a new one", exc)
        await message.answer(text, reply_markup=reply_markup)


async def answer_callback(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest:
        # Duplicate / late callback answers are harmless
        pass
