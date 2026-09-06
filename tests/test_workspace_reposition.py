from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteMessage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot_ui.callbacks import OpenCB
from bot_ui.views import View
from bot_ui.workspace import present, present_from_callback, workspace_needs_reposition
from database.db import Database
from database.entities import AccountRepository, ClientTeamRepository
from database.repository import ShipmentRepository
from database.sessions import BotSessionRepository
from handlers.workspace import cb_home, cb_open_from_reminder, cmd_menu
from services.reminder_worker import ReminderWorker
from tests.conftest import make_config


EMPTY_MARKUP = InlineKeyboardMarkup(inline_keyboard=[])


def _view(name: str, text: str) -> View:
    return View(text=text, markup=EMPTY_MARKUP, name=name)


def _bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(DeleteMessage(chat_id=1, message_id=1), text)


class FakeBot:
    def __init__(
        self,
        *,
        next_id: int = 100,
        fail_delete: bool = False,
        fail_send: bool = False,
        edit_error: str | None = None,
    ) -> None:
        self.next_id = next_id
        self.fail_delete = fail_delete
        self.fail_send = fail_send
        self.edit_error = edit_error
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.deleted: list[tuple[int, int]] = []
        self.markup_edits: list[dict] = []
        self.messages: dict[int, dict] = {}

    def seed_message(self, message_id: int, text: str = "workspace") -> None:
        self.messages[message_id] = {"text": text, "reply_markup": EMPTY_MARKUP}

    async def send_message(self, chat_id, text, reply_markup=None):
        if self.fail_send:
            raise _bad_request("can't send messages")
        self.next_id += 1
        while self.next_id in self.messages:
            self.next_id += 1
        rec = {
            "chat_id": chat_id,
            "message_id": self.next_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        self.sent.append(rec)
        self.messages[self.next_id] = rec
        return SimpleNamespace(message_id=self.next_id, chat=SimpleNamespace(id=chat_id))

    async def edit_message_text(self, *, chat_id, message_id, text, reply_markup=None):
        if self.edit_error == "not_found":
            raise TelegramNotFound(DeleteMessage(chat_id=chat_id, message_id=message_id), "Not Found")
        if self.edit_error:
            raise _bad_request(self.edit_error)
        if message_id not in self.messages:
            raise _bad_request("message to edit not found")
        rec = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        self.edited.append(rec)
        self.messages[message_id] = rec

    async def delete_message(self, *, chat_id, message_id):
        if self.fail_delete:
            raise _bad_request("message can't be deleted")
        self.deleted.append((chat_id, message_id))
        self.messages.pop(message_id, None)

    async def edit_message_reply_markup(self, *, chat_id, message_id, reply_markup=None):
        self.markup_edits.append(
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
        )

    async def set_chat_menu_button(self, **_kwargs) -> None:
        return None


async def _repos(tmp_path):
    db = Database(tmp_path / "reposition.db")
    await db.connect()
    return (
        db,
        ShipmentRepository(db),
        AccountRepository(db),
        ClientTeamRepository(db),
        BotSessionRepository(db),
    )


async def _seed_workspace(
    sessions, *, user_id=111, chat_id=111, message_id=10, current_view="home"
) -> None:
    await sessions.upsert(
        telegram_user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        current_view=current_view,
    )


def _message(*, message_id: int, chat_id: int = 111, text: str = "notice") -> Message:
    message = AsyncMock(spec=Message)
    message.message_id = message_id
    message.chat = SimpleNamespace(id=chat_id)
    message.text = text
    message.reply_markup = EMPTY_MARKUP
    return message


def _callback(
    bot: FakeBot,
    *,
    message_id: int,
    user_id: int = 111,
    chat_id: int = 111,
    text: str = "notice",
) -> CallbackQuery:
    callback = AsyncMock(spec=CallbackQuery)
    callback.bot = bot
    callback.from_user = SimpleNamespace(id=user_id)
    callback.message = _message(message_id=message_id, chat_id=chat_id, text=text)
    callback.answer = AsyncMock()
    return callback


def _command_message(
    bot: FakeBot,
    *,
    text: str = "/menu",
    message_id: int = 99,
    user_id: int = 111,
    chat_id: int = 111,
    fail_delete: bool = False,
) -> Message:
    message = AsyncMock(spec=Message)
    message.message_id = message_id
    message.chat = SimpleNamespace(id=chat_id)
    message.from_user = SimpleNamespace(id=user_id)
    message.text = text
    message.bot = bot

    async def _delete() -> None:
        if fail_delete:
            raise _bad_request("message can't be deleted")
        await bot.delete_message(chat_id=chat_id, message_id=message_id)

    message.delete = _delete
    return message


def _state(*, user_id: int = 111, chat_id: int = 111) -> FSMContext:
    storage = MemoryStorage()
    return FSMContext(
        storage=storage,
        key=StorageKey(bot_id=1, chat_id=chat_id, user_id=user_id),
    )


@pytest.mark.asyncio
async def test_reminder_check_shipment_does_not_edit_or_delete_notice(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        bot.seed_message(10, "HOME")
        bot.seed_message(21, "REMINDER")
        notice = _message(message_id=21, text="REMINDER")

        mid = await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("details", "SHIPMENT DETAILS"),
            prefer_message_id=notice.message_id,
            from_notice=True,
        )

        assert 21 in bot.messages
        assert bot.messages[21]["text"] == "REMINDER"
        assert (111, 21) not in bot.deleted
        assert all(edit["message_id"] != 21 for edit in bot.edited)
        assert mid == bot.sent[-1]["message_id"]
        assert mid != 21
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == mid
        assert not workspace_needs_reposition(session)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reminder_open_moves_workspace_below_notice(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        bot.seed_message(10, "HOME / MENU")
        bot.seed_message(21, "REMINDER")
        callback = _callback(bot, message_id=21, text="REMINDER")

        await present_from_callback(
            callback,
            sessions,
            _view("details", "SHIPMENT DETAILS"),
            from_notice=True,
        )

        assert bot.deleted == [(111, 10)]
        assert len(bot.sent) == 1
        assert bot.sent[0]["text"] == "SHIPMENT DETAILS"
        assert bot.sent[0]["message_id"] > 21
        assert not bot.edited
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "details"
        assert session["needs_reposition"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_old_workspace_button_moves_panel_below_reminder(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        bot.seed_message(10, "HOME / MENU")
        callback = _callback(bot, message_id=10, text="HOME / MENU")

        await present_from_callback(
            callback,
            sessions,
            _view("home", "UPDATED WORKSPACE / MENU"),
        )

        assert bot.deleted == [(111, 10)]
        assert len(bot.sent) == 1
        assert bot.sent[0]["text"] == "UPDATED WORKSPACE / MENU"
        assert bot.sent[0]["message_id"] > 20
        assert not bot.edited
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["message_id"] != 10
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_subsequent_navigation_edits_workspace_in_place(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        first = _callback(bot, message_id=21, text="REMINDER")
        await present_from_callback(
            first,
            sessions,
            _view("details", "SHIPMENT DETAILS"),
            from_notice=True,
        )
        workspace_id = bot.sent[0]["message_id"]
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == workspace_id

        second = _callback(bot, message_id=workspace_id, text="SHIPMENT DETAILS")
        await present_from_callback(
            second,
            sessions,
            _view("home", "HOME AFTER NAV"),
        )

        assert len(bot.sent) == 1
        assert len(bot.edited) == 1
        assert bot.edited[0]["message_id"] == workspace_id
        assert bot.edited[0]["text"] == "HOME AFTER NAV"
        assert bot.deleted == [(111, 10)]
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == workspace_id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_multiple_reminders_stay_untouched_when_workspace_moves(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=30)
        bot.seed_message(10, "HOME")
        bot.seed_message(21, "REMINDER A")
        bot.seed_message(22, "REMINDER B")
        callback = _callback(bot, message_id=10, text="HOME")

        await present_from_callback(
            callback,
            sessions,
            _view("home", "WORKSPACE BELOW BOTH"),
        )

        assert bot.messages[21]["text"] == "REMINDER A"
        assert bot.messages[22]["text"] == "REMINDER B"
        assert (111, 21) not in bot.deleted
        assert (111, 22) not in bot.deleted
        assert all(edit["message_id"] not in {21, 22} for edit in bot.edited)
        assert bot.deleted == [(111, 10)]
        assert bot.sent[0]["message_id"] > 22
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_opening_from_either_reminder_keeps_one_active_workspace(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=30)
        bot.seed_message(21, "REMINDER A")
        bot.seed_message(22, "REMINDER B")

        await present_from_callback(
            _callback(bot, message_id=21, text="REMINDER A"),
            sessions,
            _view("details", "DETAILS FROM A"),
            from_notice=True,
        )
        first_workspace = bot.sent[0]["message_id"]

        await present_from_callback(
            _callback(bot, message_id=22, text="REMINDER B"),
            sessions,
            _view("details", "DETAILS FROM B"),
            from_notice=True,
        )

        assert bot.messages[21]["text"] == "REMINDER A"
        assert bot.messages[22]["text"] == "REMINDER B"
        assert (111, 21) not in bot.deleted
        assert (111, 22) not in bot.deleted
        assert len(bot.sent) == 1
        assert bot.edited[0]["message_id"] == first_workspace
        assert bot.edited[0]["text"] == "DETAILS FROM B"
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == first_workspace
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_normal_navigation_reuses_one_workspace_message(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot()
        bot.seed_message(10, "HOME")
        for text, name in (
            ("SHIPMENT DETAILS", "details"),
            ("EDIT SHIPMENT", "edit"),
            ("SHIPMENT DETAILS", "details"),
            ("HOME", "home"),
        ):
            callback = _callback(bot, message_id=10, text="panel")
            await present_from_callback(callback, sessions, _view(name, text))
        assert bot.sent == []
        assert bot.deleted == []
        assert [edit["text"] for edit in bot.edited] == [
            "SHIPMENT DETAILS",
            "EDIT SHIPMENT",
            "SHIPMENT DETAILS",
            "HOME",
        ]
        assert all(edit["message_id"] == 10 for edit in bot.edited)
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == 10
        assert session["current_view"] == "home"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_present_edits_in_place_when_workspace_is_latest(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot()
        bot.seed_message(10, "HOME")
        mid = await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("home", "STILL HOME"),
        )
        assert mid == 10
        assert bot.sent == []
        assert bot.deleted == []
        assert bot.edited[0]["message_id"] == 10
        assert bot.edited[0]["text"] == "STILL HOME"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_edd_worker_marks_workspace_for_reposition(tmp_path) -> None:
    db, repo, accounts, _teams, sessions = await _repos(tmp_path)
    try:
        account = await accounts.create("Ops")
        await repo.create(
            country="DE",
            name="Oner Active",
            clone_name="Oner",
            status="enroute",
            created_by=111,
            account_id=account["id"],
            unit_quantity=5,
            expected_delivery_date="2026-09-10",
            require_account=True,
        )
        await _seed_workspace(sessions, message_id=10)
        from datetime import datetime, timezone

        due = await repo.due_edd_reminders(
            now=datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc),
            tz_name="UTC",
            reminder_hour=9,
        )
        bot = FakeBot(next_id=40)
        worker = ReminderWorker(
            bot=bot,
            repo=repo,
            recipient_ids=frozenset({111}),
            tz_name="UTC",
            reminder_hour=9,
            sessions=sessions,
        )
        await worker._deliver_edd(due[0])
        assert bot.sent
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == 10
        assert workspace_needs_reposition(session) is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_open_shipment_handler_preserves_reminder_and_repositions(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        account = await accounts.create("Ops")
        shipment = await repo.create(
            country="DE",
            name="Oner Active",
            clone_name="Oner",
            status="enroute",
            account_id=account["id"],
            require_account=True,
        )
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        bot.seed_message(21, "🇩🇪 reminder")
        callback = _callback(bot, message_id=21, text="🇩🇪 reminder")
        await cb_open_from_reminder(
            callback,
            OpenCB(i=shipment["id"]),
            _state(),
            repo,
            accounts,
            teams,
            sessions,
            make_config(tmp_path),
        )
        assert bot.messages[21]["text"] == "🇩🇪 reminder"
        assert (111, 21) not in bot.deleted
        assert bot.deleted == [(111, 10)]
        assert bot.sent
        assert "Oner Active" in bot.sent[0]["text"]
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "details"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_home_button_on_old_workspace_repositions_after_reminder(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await accounts.create("Ops")
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        callback = _callback(bot, message_id=10, text="HOME")
        await cb_home(
            callback,
            _state(),
            repo,
            accounts,
            teams,
            sessions,
            make_config(tmp_path),
        )
        assert bot.deleted == [(111, 10)]
        assert bot.sent
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "home"
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_menu_reanchors_existing_workspace_even_if_editable(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10, current_view="details")
        bot = FakeBot()
        bot.seed_message(10, "SHIPMENT DETAILS")
        message = _command_message(bot, text="/menu", message_id=50)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.edited == []
        assert len(bot.sent) == 1
        assert (111, 10) in bot.deleted
        assert bot.deleted[-1] == (111, 50)
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["message_id"] != 10
        assert session["current_view"] == "home"
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_menu_after_reminder_repositions_home(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20)
        bot.seed_message(10, "OLD WORKSPACE")
        bot.seed_message(21, "REMINDER")
        message = _command_message(bot, text="/menu", message_id=50)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.edited == []
        assert bot.deleted == [(111, 10), (111, 50)]
        assert len(bot.sent) == 1
        assert bot.messages[21]["text"] == "REMINDER"
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "home"
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_menu_after_reminder_without_reposition_flag(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot(next_id=20)
        bot.seed_message(10, "OLD WORKSPACE")
        bot.seed_message(21, "REMINDER")
        message = _command_message(bot, text="/menu", message_id=50)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.edited == []
        assert bot.messages[21]["text"] == "REMINDER"
        assert (111, 21) not in bot.deleted
        assert (111, 10) in bot.deleted
        assert len(bot.sent) == 1
        assert bot.sent[0]["message_id"] > 21
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_menu_with_no_session_sends_home(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        bot = FakeBot(next_id=20)
        bot.seed_message(21, "REMINDER")
        message = _command_message(bot, text="/menu", message_id=50)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert len(bot.sent) == 1
        assert bot.sent[0]["message_id"] > 21
        assert bot.messages[21]["text"] == "REMINDER"
        assert bot.deleted == [(111, 50)]
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "home"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_start_reanchors_existing_workspace(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot()
        bot.seed_message(10, "HOME")
        message = _command_message(bot, text="/start", message_id=51)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.edited == []
        assert len(bot.sent) == 1
        assert (111, 10) in bot.deleted
        assert (await sessions.get(111))["message_id"] == bot.sent[0]["message_id"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_menu_command_delete_failure_still_presents(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot()
        bot.seed_message(10, "SHIPMENT")
        message = _command_message(bot, text="/menu", message_id=50, fail_delete=True)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.sent
        assert bot.edited == []
        assert (111, 50) not in bot.deleted
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "home"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_workspace_delete_failure_strips_and_still_sends(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20, fail_delete=True)
        bot.seed_message(10, "OLD WORKSPACE")
        bot.seed_message(21, "REMINDER")
        mid = await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("home", "NEW HOME"),
        )
        assert bot.deleted == []
        assert any(
            edit["message_id"] == 10 and edit["reply_markup"] is None
            for edit in bot.markup_edits
        )
        assert bot.sent[0]["text"] == "NEW HOME"
        assert mid == bot.sent[0]["message_id"]
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == mid
        assert session["message_id"] != 10
        assert workspace_needs_reposition(session) is False
        assert bot.messages[21]["text"] == "REMINDER"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_missing_workspace_recovers_by_sending_one_new_message(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot(next_id=20)
        mid = await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("home", "RECOVERED HOME"),
        )
        assert bot.edited == []
        assert len(bot.sent) == 1
        assert mid == bot.sent[0]["message_id"]
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == mid
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_needs_reposition_survives_repository_reload(tmp_path) -> None:
    db_path = tmp_path / "reposition.db"
    db = Database(db_path)
    await db.connect()
    try:
        sessions = BotSessionRepository(db)
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
    finally:
        await db.close()

    restarted = Database(db_path)
    await restarted.connect()
    try:
        sessions = BotSessionRepository(restarted)
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == 10
        assert workspace_needs_reposition(session) is True
        bot = FakeBot(next_id=20)
        bot.seed_message(10, "OLD")
        bot.seed_message(21, "REMINDER")
        await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("home", "HOME AFTER RESTART"),
        )
        assert bot.deleted == [(111, 10)]
        assert bot.sent[0]["text"] == "HOME AFTER RESTART"
        reloaded = await sessions.get(111)
        assert reloaded is not None
        assert reloaded["message_id"] == bot.sent[0]["message_id"]
        assert workspace_needs_reposition(reloaded) is False
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_cleared_chat_stale_session_menu_sends_new_home(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=12345)
        bot = FakeBot(next_id=20)
        # Telegram may still accept edits to the stored ID after a cleared chat.
        bot.seed_message(12345, "INVISIBLE OLD WORKSPACE")
        message = _command_message(bot, text="/menu", message_id=50)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.edited == []
        assert len(bot.sent) == 1
        assert bot.sent[0]["message_id"] != 12345
        assert (111, 50) in bot.deleted
        assert bot.deleted[-1] == (111, 50)
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "home"
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_cleared_chat_stale_session_start_sends_new_home(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=12345)
        bot = FakeBot(next_id=20, edit_error="message identifier is invalid")
        message = _command_message(bot, text="/start", message_id=51)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert len(bot.sent) == 1
        assert (111, 51) in bot.deleted
        assert bot.deleted[-1] == (111, 51)
        assert (await sessions.get(111))["message_id"] == bot.sent[0]["message_id"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stale_workspace_callback_recovers_with_one_new_message(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot(next_id=20)
        callback = _callback(bot, message_id=10, text="GONE")
        await present_from_callback(callback, sessions, _view("details", "RECOVERED DETAILS"))
        assert bot.sent
        assert bot.sent[0]["text"] == "RECOVERED DETAILS"
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "details"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_inaccessible_callback_message_recovers_workspace(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot(next_id=20)
        callback = AsyncMock(spec=CallbackQuery)
        callback.bot = bot
        callback.from_user = SimpleNamespace(id=111)
        callback.message = SimpleNamespace(message_id=10, chat=SimpleNamespace(id=111))
        callback.answer = AsyncMock()
        await cb_home(
            callback,
            _state(),
            repo,
            accounts,
            teams,
            sessions,
            make_config(tmp_path),
        )
        assert bot.sent
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == bot.sent[0]["message_id"]
        assert session["current_view"] == "home"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_command_not_deleted_when_presentation_fails(tmp_path) -> None:
    db, repo, accounts, teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=12345)
        bot = FakeBot(next_id=20, fail_send=True)
        message = _command_message(bot, text="/menu", message_id=50)
        await cmd_menu(message, _state(), repo, accounts, teams, sessions, make_config(tmp_path))
        assert bot.sent == []
        assert bot.edited == []
        assert (111, 50) not in bot.deleted
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == 12345
        assert session["current_view"] == "home"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stale_buried_workspace_recovers_and_clears_flag(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        await sessions.mark_needs_reposition(111)
        bot = FakeBot(next_id=20, fail_delete=True)
        bot.seed_message(21, "REMINDER")
        mid = await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("home", "NEW HOME"),
        )
        assert bot.sent[0]["text"] == "NEW HOME"
        assert mid == bot.sent[0]["message_id"]
        assert bot.messages[21]["text"] == "REMINDER"
        session = await sessions.get(111)
        assert session is not None
        assert session["message_id"] == mid
        assert workspace_needs_reposition(session) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_telegram_not_found_is_treated_as_stale_workspace(tmp_path) -> None:
    db, _repo, _accounts, _teams, sessions = await _repos(tmp_path)
    try:
        await _seed_workspace(sessions, message_id=10)
        bot = FakeBot(next_id=20, edit_error="not_found")
        mid = await present(
            bot,
            sessions,
            user_id=111,
            chat_id=111,
            view=_view("home", "HOME AFTER 404"),
        )
        assert mid == bot.sent[0]["message_id"]
        assert bot.sent[0]["text"] == "HOME AFTER 404"
        assert (await sessions.get(111))["message_id"] == mid
    finally:
        await db.close()
