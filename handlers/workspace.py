"""Primary Telegram workspace: one interactive message per user."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, MenuButtonDefault, Message

from bot_ui.calendar import shift_month
from bot_ui.callbacks import DateCB, NavCB, OpenCB, PickCB, RemCB, ShipCB
from bot_ui.draft import draft_missing, new_draft
from bot_ui.keyboards import iso_from_shipment_field
from bot_ui.nav import current_frame, get_nav, goto, pop, push, replace_top, reset_home, set_nav
from bot_ui.parse import parse_name, parse_unit_quantity_text
from bot_ui.views import (
    View,
    current_picker_value,
    picker_columns,
    picker_items_for,
    view_account_shipments,
    view_accounts,
    view_all,
    view_archive,
    view_archive_confirm,
    view_calendar,
    view_delivered_confirm,
    view_details,
    view_draft,
    view_history,
    view_home,
    country_picker_source,
    view_name_prompt,
    view_new_account_prompt,
    view_new_team_prompt,
    view_new_value_prompt,
    view_note_prompt,
    view_picker,
    view_picker_search_prompt,
    view_reminder,
    view_reminder_time,
    view_search_prompt,
    view_search_results,
    view_unit_quantity_prompt,
)
from bot_ui.workspace import (
    OUTDATED_ALERT,
    is_outdated_workspace,
    present,
    present_from_callback,
    refresh_other_homes,
    strip_keyboard,
    try_delete_message,
)
from config import Config
from database.entities import AccountRepository, ClientTeamRepository, MAX_NAME_LEN
from database.repository import (
    MAX_NOTE_LEN,
    MAX_SHIPMENT_NAME_LEN,
    ShipmentRepository,
)
from domain.countries import country_code_from_index
from database.sessions import BotSessionRepository
from domain.status import OPERATIONAL_STATUSES, STATUS_FROM_SHORT
from states.workspace import WorkspaceStates
from utils.dates import today_in_timezone
from utils.telegram import answer_callback

logger = logging.getLogger(__name__)

router = Router(name="workspace")

HOST_VIEWS = {
    "home",
    "details",
    "draft",
    "search",
    "list",
    "accounts",
    "acct_ships",
    "archive",
}

DATE_KEYS = {
    "lb": "label_creation_date",
    "sc": "scanned_in_date",
    "ed": "expected_delivery_date",
}

DATE_TITLES = {
    "lb": "Label creation",
    "sc": "Scanned in",
    "ed": "Expected delivery",
}


def _tz(config: Config) -> str:
    return config.app_timezone


async def _reset_chat_menu(message: Message) -> None:
    try:
        await message.bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonDefault(),
        )
    except Exception:
        logger.debug("Could not reset per-chat menu button", exc_info=True)


async def render_frame(
    frame: dict[str, Any],
    *,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    state: FSMContext,
    config: Config,
) -> View:
    view_name = frame.get("v") or "home"
    tz_name = _tz(config)
    if view_name == "home":
        return await view_home(
            repo,
            accounts,
            tz_name=tz_name,
            page=int(frame.get("p") or 0),
        )
    if view_name == "details":
        view = await view_details(repo, int(frame["i"]), tz_name=tz_name)
        if view is None:
            await reset_home(state)
            return await view_home(repo, accounts, tz_name=tz_name)
        return view
    if view_name == "draft":
        data = await state.get_data()
        return await view_draft(data.get("draft") or new_draft(), accounts, teams, tz_name=tz_name)
    if view_name == "search":
        data = await state.get_data()
        query = str(frame.get("q") or data.get("search_query") or "")
        return await view_search_results(repo, query, int(frame.get("p") or 0), tz_name=tz_name)
    if view_name == "list":
        status = frame.get("st") or None
        return await view_all(repo, status=status, page=int(frame.get("p") or 0), tz_name=tz_name)
    if view_name == "accounts":
        return await view_accounts(accounts, page=int(frame.get("p") or 0))
    if view_name == "acct_ships":
        unassigned = bool(frame.get("u"))
        account_id = None if unassigned else int(frame.get("i") or 0)
        title = "No account"
        if not unassigned and account_id:
            account = await accounts.get_by_id(account_id)
            title = account["name"] if account else f"#{account_id}"
        return await view_account_shipments(
            repo,
            account_id=account_id,
            unassigned=unassigned,
            page=int(frame.get("p") or 0),
            tz_name=tz_name,
            title=title,
        )
    if view_name == "archive":
        return await view_archive(repo, int(frame.get("p") or 0), tz_name=tz_name)
    if view_name == "history":
        view = await view_history(repo, int(frame["i"]), int(frame.get("p") or 0))
        if view is None:
            await reset_home(state)
            return await view_home(repo, accounts, tz_name=tz_name)
        return view
    if view_name == "reminder":
        view = await view_reminder(repo, int(frame["i"]), tz_name=tz_name)
        if view is None:
            await reset_home(state)
            return await view_home(repo, accounts, tz_name=tz_name)
        return view
    if view_name == "reminder_time":
        when = date(int(frame["y"]), int(frame["m"]), int(frame["d"]))
        return view_reminder_time(int(frame["i"]), when)
    if view_name == "pick":
        return await _render_picker(frame, repo=repo, accounts=accounts, teams=teams, state=state)
    if view_name in {"date", "cal"}:
        return await _render_calendar(frame, repo=repo, state=state, tz_name=tz_name)
    if view_name == "del_confirm":
        shipment = await repo.get_by_id(int(frame["i"]))
        if shipment is None:
            await reset_home(state)
            return await view_home(repo, accounts, tz_name=tz_name)
        return view_delivered_confirm(shipment)
    if view_name == "arc_confirm":
        shipment = await repo.get_by_id(int(frame["i"]))
        if shipment is None:
            await reset_home(state)
            return await view_home(repo, accounts, tz_name=tz_name)
        return view_archive_confirm(shipment)
    return await view_home(repo, accounts, tz_name=tz_name)


async def _render_picker(
    frame: dict[str, Any],
    *,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    state: FSMContext,
) -> View:
    kind = str(frame.get("k") or "acc")
    target = str(frame.get("t") or "s")
    shipment_id = int(frame.get("i") or 0)
    page = int(frame.get("p") or 0)
    data = await state.get_data()
    query = data.get("picker_query") if data.get("picker_kind") == kind else None
    section_label = None
    extra_nav = None
    if kind == "co":
        items, section_label = await country_picker_source(
            repo, query=query, show_all=bool(frame.get("all"))
        )
        query = None
        if not frame.get("all"):
            extra_nav = [
                InlineKeyboardButton(
                    text="🌍 All countries",
                    callback_data=PickCB(
                        x="a", k=kind, t=target, i=shipment_id, p=0
                    ).pack(),
                )
            ]
    else:
        items = await picker_items_for(kind, repo, accounts, teams)
    shipment = await repo.get_by_id(shipment_id) if target == "s" and shipment_id else None
    draft = data.get("draft") if target == "d" else None
    current_id, current_label = await current_picker_value(
        kind=kind, target=target, shipment=shipment, draft=draft
    )
    if kind == "acc" and target == "d" and current_id and not current_label:
        account = await accounts.get_by_id(current_id)
        current_label = account["name"] if account else None
    if kind == "tm" and target == "d" and current_id and not current_label:
        team = await teams.get_by_id(current_id)
        current_label = team["name"] if team else None
    allow_new = kind in {"acc", "tm"}
    allow_clear = kind == "tm"
    allow_search = kind in {"acc", "tm", "co"}
    return await view_picker(
        kind=kind,
        target=target,
        shipment_id=shipment_id,
        page=page,
        query=query,
        current_id=current_id,
        current_label=current_label,
        items=items,
        allow_new=allow_new,
        allow_search=allow_search,
        allow_clear=allow_clear,
        columns=picker_columns(kind, items),
        section_label=section_label,
        extra_nav=extra_nav,
    )


async def _source_date(
    frame: dict[str, Any],
    *,
    repo: ShipmentRepository,
    state: FSMContext,
) -> str | None:
    field = str(frame.get("f") or "ed")
    target = str(frame.get("t") or "s")
    if field == "rm":
        return None
    if target == "d":
        data = await state.get_data()
        draft = data.get("draft") or {}
        return draft.get(DATE_KEYS.get(field, ""))
    shipment_id = int(frame.get("i") or 0)
    shipment = await repo.get_by_id(shipment_id)
    if shipment is None:
        return None
    return iso_from_shipment_field(shipment, field)


async def _calendar_frame(
    *,
    field: str,
    target: str,
    shipment_id: int,
    repo: ShipmentRepository,
    state: FSMContext,
    tz_name: str,
) -> dict[str, Any]:
    today = today_in_timezone(tz_name)
    current = await _source_date(
        {"f": field, "t": target, "i": shipment_id},
        repo=repo,
        state=state,
    )
    if current:
        try:
            parsed = date.fromisoformat(current)
            year, month = parsed.year, parsed.month
        except ValueError:
            year, month = today.year, today.month
    else:
        year, month = today.year, today.month
    return {
        "v": "cal",
        "f": field,
        "t": target,
        "i": shipment_id,
        "y": year,
        "m": month,
    }


async def _render_calendar(frame, *, repo, state, tz_name: str) -> View:
    current = await _source_date(frame, repo=repo, state=state)
    today = today_in_timezone(tz_name)
    year = int(frame.get("y") or 0)
    month = int(frame.get("m") or 0)
    if year < 1 or month < 1:
        if current:
            try:
                parsed = date.fromisoformat(current)
                year, month = parsed.year, parsed.month
            except ValueError:
                year, month = today.year, today.month
        else:
            year, month = today.year, today.month
    return view_calendar(
        field=str(frame.get("f") or "ed"),
        target=str(frame.get("t") or "s"),
        shipment_id=int(frame.get("i") or 0),
        year=year,
        month=month,
        current=current,
        tz_name=tz_name,
    )


async def show_current(
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
    from_notice: bool = False,
    force_new: bool = False,
) -> None:
    frame = await current_frame(state)
    view = await render_frame(
        frame, repo=repo, accounts=accounts, teams=teams, state=state, config=config
    )
    if callback is not None:
        await present_from_callback(
            callback, sessions, view, from_notice=from_notice
        )
        return
    if message is None or message.from_user is None:
        return
    await present(
        message.bot,
        sessions,
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        view=view,
        force_new=force_new,
    )


async def show_home(
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    await state.set_state(None)
    await reset_home(state)
    await show_current(
        callback=callback,
        message=message,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


async def notify_homes(
    callback: CallbackQuery,
    sessions: BotSessionRepository,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    config: Config,
) -> None:
    user = callback.from_user
    if user is None:
        return
    await refresh_other_homes(
        callback.bot,
        sessions,
        repo,
        accounts,
        except_user_id=user.id,
        tz_name=_tz(config),
    )


async def pop_to_host(state: FSMContext) -> dict[str, Any]:
    nav = await get_nav(state)
    while len(nav) > 1 and nav[-1].get("v") not in HOST_VIEWS:
        nav.pop()
    if not nav:
        nav = [{"v": "home", "p": 0}]
    await set_nav(state, nav)
    return dict(nav[-1])


async def stale(callback: CallbackQuery, sessions: BotSessionRepository) -> bool:
    if callback.message is None or not isinstance(callback.message, Message):
        await answer_callback(callback, "Message unavailable.", show_alert=True)
        return True
    if callback.from_user is None:
        return True
    session = await sessions.get(callback.from_user.id)
    if is_outdated_workspace(session, callback.message):
        await answer_callback(callback, OUTDATED_ALERT, show_alert=True)
        await strip_keyboard(
            callback.bot, callback.message.chat.id, callback.message.message_id
        )
        return True
    return False


async def apply_date_value(
    *,
    repo: ShipmentRepository,
    state: FSMContext,
    target: str,
    shipment_id: int,
    field: str,
    iso: str | None,
) -> str | None:
    key = DATE_KEYS.get(field)
    if key is None:
        return "Unknown date field"
    if target == "d":
        data = await state.get_data()
        draft = dict(data.get("draft") or new_draft())
        draft[key] = iso
        await state.update_data(draft=draft)
        return None
    if not shipment_id:
        return "Shipment not found"
    try:
        updated = await repo.update_fields(shipment_id, **{key: iso})
    except ValueError as exc:
        return str(exc)
    if updated is None:
        return "Shipment not available"
    return None


# --- Commands --------------------------------------------------------------


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_menu(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    await state.clear()
    await reset_home(state)
    await _reset_chat_menu(message)
    view = await view_home(repo, accounts, tz_name=_tz(config))
    user = message.from_user
    if user is None:
        return
    await present(
        message.bot,
        sessions,
        user_id=user.id,
        chat_id=message.chat.id,
        view=view,
        force_new=True,
    )


@router.message(Command("add"))
async def cmd_add(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    await state.set_state(None)
    await state.update_data(draft=new_draft(), creating=False, picker_query=None)
    await goto(state, {"v": "home"}, {"v": "draft"})
    await show_current(
        message=message,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
        force_new=True,
    )


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    del repo, accounts, teams
    await state.set_state(WorkspaceStates.waiting_input)
    await state.update_data(input_kind="search")
    user = message.from_user
    if user is None:
        return
    await present(
        message.bot,
        sessions,
        user_id=user.id,
        chat_id=message.chat.id,
        view=view_search_prompt(),
        force_new=True,
    )
    await sessions.set_view(user.id, "input")


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    current = await state.get_state()
    if current is None:
        await show_current(
            message=message,
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
            sessions=sessions,
            config=config,
            force_new=True,
        )
        return
    await state.set_state(None)
    await state.update_data(input_kind=None, picker_query=None)
    await show_current(
        message=message,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
        force_new=True,
    )


# --- Navigation callbacks --------------------------------------------------


@router.callback_query(NavCB.filter(F.x == "np"))
async def cb_noop(callback: CallbackQuery) -> None:
    await answer_callback(callback)


@router.callback_query(NavCB.filter(F.x == "hm"))
async def cb_home(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await show_home(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "rf"))
async def cb_refresh(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "hp"))
async def cb_home_page(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await replace_top(state, {"v": "home", "p": callback_data.p})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "bk"))
async def cb_back(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.set_state(None)
    await pop(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "ic"))
async def cb_input_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.set_state(None)
    await state.update_data(input_kind=None)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "ad"))
async def cb_add(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.set_state(None)
    await state.update_data(draft=new_draft(), creating=False, picker_query=None)
    current = await current_frame(state)
    home_page = int(current.get("p") or 0) if current.get("v") == "home" else 0
    await goto(state, {"v": "home", "p": home_page}, {"v": "draft"})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "cx"))
async def cb_cancel_draft(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.update_data(draft=None, creating=False)
    await show_home(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "cr"))
async def cb_create(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    data = await state.get_data()
    draft = data.get("draft") or {}
    missing = draft_missing(draft)
    if missing:
        await answer_callback(
            callback,
            "Missing: " + ", ".join(missing),
            show_alert=True,
        )
        return
    if data.get("creating"):
        await answer_callback(callback, "Already creating…")
        return
    await state.update_data(creating=True)
    user = callback.from_user
    try:
        shipment = await repo.create(
            country=str(draft["country"]),
            name=str(draft["name"]),
            clone_name="",
            status=str(draft.get("status") or "preparing"),
            created_by=user.id if user else None,
            note=draft.get("note"),
            expected_delivery_date=draft.get("expected_delivery_date"),
            account_id=int(draft["account_id"]),
            client_team_id=draft.get("client_team_id"),
            unit_quantity=draft.get("unit_quantity"),
            label_creation_date=draft.get("label_creation_date"),
            scanned_in_date=draft.get("scanned_in_date"),
            require_account=True,
        )
    except ValueError as exc:
        await state.update_data(creating=False)
        await answer_callback(callback, str(exc)[:180], show_alert=True)
        return
    except Exception:
        await state.update_data(creating=False)
        logger.exception("Create shipment failed")
        await answer_callback(callback, "Could not create shipment.", show_alert=True)
        return
    await answer_callback(callback)
    await state.update_data(draft=None, creating=False)
    await goto(state, {"v": "home"}, {"v": "details", "i": shipment["id"]})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(NavCB.filter(F.x == "se"))
async def cb_search(
    callback: CallbackQuery,
    state: FSMContext,
    sessions: BotSessionRepository,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.set_state(WorkspaceStates.waiting_input)
    await state.update_data(input_kind="search")
    await present_from_callback(callback, sessions, view_search_prompt())


@router.callback_query(NavCB.filter(F.x == "sp"))
async def cb_search_page(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await replace_top(state, {**(await current_frame(state)), "p": callback_data.p, "v": "search"})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "al"))
async def cb_all(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    status = STATUS_FROM_SHORT.get(callback_data.f) if callback_data.f else None
    frame = {"v": "list", "st": status, "p": callback_data.p}
    current = await current_frame(state)
    if current.get("v") == "list":
        await replace_top(state, frame)
    else:
        await push(state, frame)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "as"))
async def cb_accounts(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    current = await current_frame(state)
    frame = {"v": "accounts", "p": callback_data.p}
    if current.get("v") == "accounts":
        await replace_top(state, frame)
    else:
        await push(state, frame)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "ah"))
async def cb_account_shipments(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    unassigned = callback_data.f == "u"
    frame = {
        "v": "acct_ships",
        "i": callback_data.i,
        "u": unassigned,
        "p": callback_data.p,
    }
    current = await current_frame(state)
    if current.get("v") == "acct_ships":
        await replace_top(state, frame)
    else:
        await push(state, frame)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x == "ar"))
async def cb_archive_list(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    frame = {"v": "archive", "p": callback_data.p}
    current = await current_frame(state)
    if current.get("v") == "archive":
        await replace_top(state, frame)
    else:
        await push(state, frame)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(NavCB.filter(F.x.in_({"wt", "nt", "nm"})))
async def cb_draft_text_fields(
    callback: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    sessions: BotSessionRepository,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    kind = {"wt": "unit_quantity", "nt": "note", "nm": "name"}[callback_data.x]
    await state.set_state(WorkspaceStates.waiting_input)
    await state.update_data(input_kind=kind, input_target="d", input_shipment_id=0)
    data = await state.get_data()
    draft = data.get("draft") or {}
    if kind == "unit_quantity":
        view = view_unit_quantity_prompt(draft.get("unit_quantity"), target="d", shipment_id=0)
    elif kind == "name":
        view = view_name_prompt(draft.get("name"))
    else:
        view = view_note_prompt()
    await present_from_callback(callback, sessions, view)


@router.callback_query(NavCB.filter(F.x == "w0"))
async def cb_draft_clear_unit_quantity(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    data = await state.get_data()
    draft = dict(data.get("draft") or new_draft())
    draft["unit_quantity"] = None
    await state.update_data(draft=draft)
    await state.set_state(None)
    await answer_callback(callback, "Unit quantity cleared")
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


# --- Shipment callbacks ----------------------------------------------------


@router.callback_query(ShipCB.filter(F.x == "vw"))
async def cb_view_shipment(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    shipment = await repo.get_by_id(callback_data.i)
    if shipment is None:
        await answer_callback(callback, "Shipment not found.", show_alert=True)
        return
    await answer_callback(callback)
    current = await current_frame(state)
    if not (current.get("v") == "details" and current.get("i") == callback_data.i):
        await push(state, {"v": "details", "i": callback_data.i})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(OpenCB.filter())
async def cb_open_from_reminder(
    callback: CallbackQuery,
    callback_data: OpenCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    shipment = await repo.get_by_id(callback_data.i)
    if shipment is None:
        await answer_callback(callback, "Shipment not found.", show_alert=True)
        return
    await answer_callback(callback)
    await goto(state, {"v": "home"}, {"v": "details", "i": callback_data.i})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
        from_notice=True,
    )


@router.callback_query(ShipCB.filter(F.x == "st"))
async def cb_status_picker(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await push(state, {"v": "pick", "k": "st", "t": "s", "i": callback_data.i, "p": 0})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(ShipCB.filter(F.x.in_({"wt", "nt", "nm"})))
async def cb_shipment_text_fields(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    sessions: BotSessionRepository,
) -> None:
    if await stale(callback, sessions):
        return
    shipment = await repo.get_by_id(callback_data.i)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        return
    await answer_callback(callback)
    kind = {"wt": "unit_quantity", "nt": "note", "nm": "name"}[callback_data.x]
    await state.set_state(WorkspaceStates.waiting_input)
    await state.update_data(
        input_kind=kind, input_target="s", input_shipment_id=callback_data.i
    )
    if kind == "unit_quantity":
        view = view_unit_quantity_prompt(
            shipment.get("unit_quantity"), target="s", shipment_id=callback_data.i
        )
    elif kind == "name":
        view = view_name_prompt(shipment.get("name"))
    else:
        view = view_note_prompt()
    await present_from_callback(callback, sessions, view)


@router.callback_query(ShipCB.filter(F.x == "w0"))
async def cb_clear_unit_quantity(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    try:
        updated = await repo.update_fields(callback_data.i, unit_quantity=None)
    except ValueError as exc:
        await answer_callback(callback, str(exc)[:180], show_alert=True)
        return
    if updated is None:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        return
    await state.set_state(None)
    await answer_callback(callback, "Unit quantity cleared")
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(ShipCB.filter(F.x == "md"))
async def cb_mark_delivered(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    shipment = await repo.get_by_id(callback_data.i)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        return
    await answer_callback(callback)
    await push(state, {"v": "del_confirm", "i": callback_data.i})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(ShipCB.filter(F.x == "my"))
async def cb_mark_delivered_yes(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    user = callback.from_user
    delivered = today_in_timezone(config.app_timezone).isoformat()
    shipment = await repo.complete(
        callback_data.i,
        changed_by=user.id if user else None,
        delivered_date=delivered,
    )
    if shipment is None:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        return
    await answer_callback(callback, "Marked delivered")
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(ShipCB.filter(F.x == "aq"))
async def cb_archive_prompt(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    shipment = await repo.get_by_id(callback_data.i)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        return
    await answer_callback(callback)
    await push(state, {"v": "arc_confirm", "i": callback_data.i})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(ShipCB.filter(F.x == "ay"))
async def cb_archive_yes(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    user = callback.from_user
    shipment = await repo.archive(
        callback_data.i, changed_by=user.id if user else None
    )
    if shipment is None:
        await answer_callback(callback, "Shipment not found.", show_alert=True)
        return
    await answer_callback(callback, "Archived")
    await show_home(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(ShipCB.filter(F.x == "rs"))
async def cb_restore(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    user = callback.from_user
    shipment = await repo.restore(
        callback_data.i, changed_by=user.id if user else None
    )
    if shipment is None:
        await answer_callback(callback, "Shipment not found.", show_alert=True)
        return
    await answer_callback(callback, "Restored")
    await replace_top(state, {"v": "details", "i": callback_data.i})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(ShipCB.filter(F.x == "hi"))
async def cb_history(
    callback: CallbackQuery,
    callback_data: ShipCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    frame = {"v": "history", "i": callback_data.i, "p": callback_data.p}
    current = await current_frame(state)
    if current.get("v") == "history":
        await replace_top(state, frame)
    else:
        await push(state, frame)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


# --- Pickers ---------------------------------------------------------------


@router.callback_query(PickCB.filter(F.x == "o"))
async def cb_picker_open(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.update_data(picker_query=None, picker_kind=callback_data.k)
    await push(
        state,
        {
            "v": "pick",
            "k": callback_data.k,
            "t": callback_data.t,
            "i": callback_data.i,
            "p": 0,
        },
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(PickCB.filter(F.x == "g"))
async def cb_picker_page(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    current = await current_frame(state)
    frame = {
        "v": "pick",
        "k": callback_data.k,
        "t": callback_data.t,
        "i": callback_data.i,
        "p": callback_data.p,
    }
    if current.get("all"):
        frame["all"] = 1
    await replace_top(state, frame)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(PickCB.filter(F.x == "a"))
async def cb_picker_all_countries(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.update_data(picker_query=None)
    await replace_top(
        state,
        {
            "v": "pick",
            "k": callback_data.k,
            "t": callback_data.t,
            "i": callback_data.i,
            "p": 0,
            "all": 1,
        },
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


async def _apply_picker(
    data: PickCB,
    *,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    changed_by: int | None = None,
) -> str | None:
    kind = data.k
    target = data.t
    selected = data.n
    fsm = await state.get_data()
    draft = dict(fsm.get("draft") or new_draft())
    if kind == "st":
        if selected < 0 or selected >= len(OPERATIONAL_STATUSES):
            return "Unknown status."
        status = OPERATIONAL_STATUSES[selected]
        if target == "d":
            draft["status"] = status
            await state.update_data(draft=draft)
            return None
        updated = await repo.update_status(data.i, status, changed_by=changed_by)
        if updated is None:
            return "Shipment not available"
        return None
    if kind in {"acc", "tm"}:
        lookup = accounts if kind == "acc" else teams
        entity = await lookup.get_by_id(selected)
        if entity is None or entity.get("archived"):
            return "Not found"
        if target == "d":
            if kind == "acc":
                draft["account_id"] = selected
            else:
                draft["client_team_id"] = selected
            await state.update_data(draft=draft)
            return None
        try:
            if kind == "acc":
                updated = await repo.update_fields(data.i, account_id=selected)
            else:
                updated = await repo.update_fields(data.i, client_team_id=selected)
        except ValueError as exc:
            return str(exc)
        if updated is None:
            return "Shipment not available"
        return None
    if kind == "co":
        code = country_code_from_index(selected)
        if code is None:
            return "Value not found"
        if target == "d":
            draft["country"] = code
            await state.update_data(draft=draft)
            return None
        try:
            updated = await repo.update_country(data.i, code)
        except ValueError as exc:
            return str(exc)
        if updated is None:
            return "Shipment not available"
        return None
    return "Unknown picker"


@router.callback_query(PickCB.filter(F.x == "s"))
async def cb_picker_select(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    error = await _apply_picker(
        callback_data,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        changed_by=callback.from_user.id if callback.from_user else None,
    )
    if error:
        await answer_callback(callback, error, show_alert=True)
        return
    await answer_callback(callback)
    await state.update_data(picker_query=None)
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    if callback_data.t == "s":
        await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(PickCB.filter(F.x == "c"))
async def cb_picker_clear(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    if callback_data.k != "tm":
        await answer_callback(callback)
        return
    if callback_data.t == "d":
        data = await state.get_data()
        draft = dict(data.get("draft") or new_draft())
        draft["client_team_id"] = None
        await state.update_data(draft=draft)
    else:
        try:
            updated = await repo.update_fields(callback_data.i, client_team_id=None)
        except ValueError as exc:
            await answer_callback(callback, str(exc)[:180], show_alert=True)
            return
        if updated is None:
            await answer_callback(callback, "Shipment not available.", show_alert=True)
            return
    await answer_callback(callback, "Cleared")
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    if callback_data.t == "s":
        await notify_homes(callback, sessions, repo, accounts, config)


@router.callback_query(PickCB.filter(F.x == "n"))
async def cb_picker_new(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    sessions: BotSessionRepository,
) -> None:
    if await stale(callback, sessions):
        return
    kind_map = {"acc": "account", "tm": "team"}
    kind = kind_map.get(callback_data.k)
    if not kind:
        await answer_callback(callback, "Cannot add a new value here.", show_alert=True)
        return
    await answer_callback(callback)
    await state.set_state(WorkspaceStates.waiting_input)
    await state.update_data(
        input_kind=kind,
        input_target=callback_data.t,
        input_shipment_id=callback_data.i,
        input_picker_kind=callback_data.k,
    )
    if kind == "account":
        view = view_new_account_prompt()
    elif kind == "team":
        view = view_new_team_prompt()
    else:
        view = view_new_value_prompt(kind)
    await present_from_callback(callback, sessions, view)


@router.callback_query(PickCB.filter(F.x == "q"))
async def cb_picker_search(
    callback: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    sessions: BotSessionRepository,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await state.set_state(WorkspaceStates.waiting_input)
    await state.update_data(
        input_kind="picker_search",
        input_picker_kind=callback_data.k,
        picker_kind=callback_data.k,
    )
    await present_from_callback(
        callback, sessions, view_picker_search_prompt(callback_data.k)
    )


# --- Dates -----------------------------------------------------------------


@router.callback_query(DateCB.filter(F.x.in_({"m", "o"})))
async def cb_open_calendar(
    callback: CallbackQuery,
    callback_data: DateCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    await push(
        state,
        await _calendar_frame(
            field=callback_data.f,
            target=callback_data.t,
            shipment_id=callback_data.i,
            repo=repo,
            state=state,
            tz_name=config.app_timezone,
        ),
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(DateCB.filter(F.x == "n"))
async def cb_calendar_month(
    callback: CallbackQuery,
    callback_data: DateCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    year, month = shift_month(callback_data.y, callback_data.m, callback_data.n)
    await replace_top(
        state,
        {
            "v": "cal",
            "f": callback_data.f,
            "t": callback_data.t,
            "i": callback_data.i,
            "y": year,
            "m": month,
        },
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


async def _handle_reminder_date(
    callback: CallbackQuery,
    callback_data: DateCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if callback_data.x == "c":
        await answer_callback(callback)
        await pop_to_host(state)
        await show_current(
            callback=callback,
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
            sessions=sessions,
            config=config,
        )
        return
    if callback_data.x == "s":
        try:
            when = date(callback_data.y, callback_data.m, callback_data.n)
        except ValueError:
            await answer_callback(callback, "Invalid date.", show_alert=True)
            return
    else:
        when = today_in_timezone(config.app_timezone) + timedelta(days=callback_data.n)
    await answer_callback(callback)
    await replace_top(
        state,
        {
            "v": "reminder_time",
            "i": callback_data.i,
            "y": when.year,
            "m": when.month,
            "d": when.day,
        },
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(DateCB.filter(F.x.in_({"q", "s", "c"})))
async def cb_date_set(
    callback: CallbackQuery,
    callback_data: DateCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    if callback_data.f == "rm":
        await _handle_reminder_date(
            callback, callback_data, state, repo, accounts, teams, sessions, config
        )
        return
    if callback_data.x == "c":
        iso = None
    elif callback_data.x == "s":
        try:
            iso = date(callback_data.y, callback_data.m, callback_data.n).isoformat()
        except ValueError:
            await answer_callback(callback, "Invalid date.", show_alert=True)
            return
    else:
        iso = (
            today_in_timezone(config.app_timezone) + timedelta(days=callback_data.n)
        ).isoformat()
    error = await apply_date_value(
        repo=repo,
        state=state,
        target=callback_data.t,
        shipment_id=callback_data.i,
        field=callback_data.f,
        iso=iso,
    )
    if error:
        await answer_callback(callback, error[:180], show_alert=True)
        return
    await answer_callback(callback)
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    if callback_data.t == "s":
        await notify_homes(callback, sessions, repo, accounts, config)


# --- Reminders -------------------------------------------------------------


def _reminder_preset(code: int, tz_name: str) -> datetime:
    if code == 1:
        return datetime.now(timezone.utc) + timedelta(hours=1)
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    if code == 2:
        local = now.replace(hour=18, minute=0, second=0, microsecond=0)
    elif code == 3:
        local = (now + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
    elif code == 4:
        local = (now + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
    else:
        raise ValueError("Unknown reminder preset")
    if local <= now:
        raise ValueError("That time is already in the past")
    return local.astimezone(timezone.utc)


@router.callback_query(RemCB.filter(F.x == "m"))
async def cb_reminder_menu(
    callback: CallbackQuery,
    callback_data: RemCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    shipment = await repo.get_by_id(callback_data.i)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        return
    await answer_callback(callback)
    await push(state, {"v": "reminder", "i": callback_data.i})
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(RemCB.filter(F.x == "q"))
async def cb_reminder_quick(
    callback: CallbackQuery,
    callback_data: RemCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    try:
        when = _reminder_preset(callback_data.n, config.app_timezone)
        user = callback.from_user
        await repo.set_reminder(
            callback_data.i, when, created_by=user.id if user else None
        )
    except ValueError as exc:
        await answer_callback(callback, str(exc)[:180], show_alert=True)
        return
    await answer_callback(callback, "Reminder set")
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(RemCB.filter(F.x == "d"))
async def cb_reminder_pick_date(
    callback: CallbackQuery,
    callback_data: RemCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    today = today_in_timezone(config.app_timezone)
    await push(
        state,
        {
            "v": "cal",
            "f": "rm",
            "t": "s",
            "i": callback_data.i,
            "y": today.year,
            "m": today.month,
        },
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(RemCB.filter(F.x == "t"))
async def cb_reminder_pick_time(
    callback: CallbackQuery,
    callback_data: RemCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await answer_callback(callback)
    today = today_in_timezone(config.app_timezone)
    await push(
        state,
        {
            "v": "reminder_time",
            "i": callback_data.i,
            "y": today.year,
            "m": today.month,
            "d": today.day,
        },
    )
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(RemCB.filter(F.x == "s"))
async def cb_reminder_set_time(
    callback: CallbackQuery,
    callback_data: RemCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    try:
        local = datetime(
            callback_data.y,
            callback_data.m,
            callback_data.d,
            callback_data.n,
            0,
            tzinfo=ZoneInfo(config.app_timezone),
        )
        when = local.astimezone(timezone.utc)
        user = callback.from_user
        await repo.set_reminder(
            callback_data.i, when, created_by=user.id if user else None
        )
    except ValueError as exc:
        await answer_callback(callback, str(exc)[:180], show_alert=True)
        return
    await answer_callback(callback, "Reminder set")
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


@router.callback_query(RemCB.filter(F.x == "x"))
async def cb_reminder_remove(
    callback: CallbackQuery,
    callback_data: RemCB,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    if await stale(callback, sessions):
        return
    await repo.cancel_active_reminders(callback_data.i)
    await repo.db.connection.commit()
    await answer_callback(callback, "Reminder removed")
    await pop_to_host(state)
    await show_current(
        callback=callback,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )


# --- Manual input ----------------------------------------------------------


async def _handle_input_kind(
    *,
    kind: str | None,
    raw: str,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    data: dict[str, Any],
) -> None:
    target = data.get("input_target") or "s"
    shipment_id = int(data.get("input_shipment_id") or 0)
    if kind == "search":
        query = raw.strip()
        if not query or query.startswith("/"):
            raise ValueError("Enter a search query.")
        await state.update_data(search_query=query)
        current = await current_frame(state)
        frame = {"v": "search", "q": query, "p": 0}
        if current.get("v") == "search":
            await replace_top(state, frame)
        else:
            await push(state, frame)
        return
    if kind == "picker_search":
        query = raw.strip()
        if query.startswith("/"):
            raise ValueError("Enter a search query.")
        await state.update_data(picker_query=query or None)
        return
    if kind == "unit_quantity":
        quantity = parse_unit_quantity_text(raw)
        if target == "d":
            draft = dict(data.get("draft") or new_draft())
            draft["unit_quantity"] = quantity
            await state.update_data(draft=draft)
            return
        updated = await repo.update_fields(shipment_id, unit_quantity=quantity)
        if updated is None:
            raise ValueError("Shipment not available")
        await pop_to_host(state)
        return
    if kind == "note":
        note = None if raw.strip() == "-" else raw.strip()
        if note is not None and len(note) > MAX_NOTE_LEN:
            raise ValueError(f"Note is too long (max {MAX_NOTE_LEN})")
        if target == "d":
            draft = dict(data.get("draft") or new_draft())
            draft["note"] = note
            await state.update_data(draft=draft)
            return
        updated = await repo.update_note(shipment_id, note)
        if updated is None:
            raise ValueError("Shipment not available")
        await pop_to_host(state)
        return
    if kind == "name":
        value = parse_name(
            raw, max_len=MAX_SHIPMENT_NAME_LEN, empty_message="Type a shipment name."
        )
        if target == "d":
            draft = dict(data.get("draft") or new_draft())
            draft["name"] = value
            await state.update_data(draft=draft)
            return
        updated = await repo.update_fields(shipment_id, name=value)
        if updated is None:
            raise ValueError("Shipment not available")
        await pop_to_host(state)
        return
    if kind == "account":
        name = parse_name(raw, max_len=MAX_NAME_LEN, empty_message="Type an account name.")
        entity = await accounts.create(name)
        if target == "d":
            draft = dict(data.get("draft") or new_draft())
            draft["account_id"] = entity["id"]
            await state.update_data(draft=draft)
        else:
            updated = await repo.update_fields(shipment_id, account_id=entity["id"])
            if updated is None:
                raise ValueError("Shipment not available")
        await pop_to_host(state)
        return
    if kind == "team":
        name = parse_name(raw, max_len=MAX_NAME_LEN, empty_message="Type a team name.")
        entity = await teams.create(name)
        if target == "d":
            draft = dict(data.get("draft") or new_draft())
            draft["client_team_id"] = entity["id"]
            await state.update_data(draft=draft)
        else:
            updated = await repo.update_fields(shipment_id, client_team_id=entity["id"])
            if updated is None:
                raise ValueError("Shipment not available")
        await pop_to_host(state)
        return
    raise ValueError("Nothing to enter. Open /menu.")


@router.message(StateFilter(WorkspaceStates.waiting_input), F.text)
async def process_input(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
    accounts: AccountRepository,
    teams: ClientTeamRepository,
    sessions: BotSessionRepository,
    config: Config,
) -> None:
    data = await state.get_data()
    kind = data.get("input_kind")
    raw = message.text or ""
    await try_delete_message(message)
    try:
        await _handle_input_kind(
            kind=kind,
            raw=raw,
            state=state,
            repo=repo,
            accounts=accounts,
            teams=teams,
            data=data,
        )
    except ValueError as exc:
        user = message.from_user
        if user is None:
            return
        prompt = view_search_prompt() if kind == "search" else view_note_prompt()
        await present(
            message.bot,
            sessions,
            user_id=user.id,
            chat_id=message.chat.id,
            view=View(
                text=f"{exc}\n\nTry again, or tap Cancel.",
                markup=prompt.markup,
                name="input",
            ),
        )
        return
    await state.set_state(None)
    await state.update_data(input_kind=None)
    await show_current(
        message=message,
        state=state,
        repo=repo,
        accounts=accounts,
        teams=teams,
        sessions=sessions,
        config=config,
    )
    if (
        kind in {"unit_quantity", "note", "name", "account", "team"}
        and data.get("input_target") == "s"
    ):
        user = message.from_user
        if user is not None:
            await refresh_other_homes(
                message.bot,
                sessions,
                repo,
                accounts,
                except_user_id=user.id,
                tz_name=_tz(config),
            )


@router.message(StateFilter(WorkspaceStates.waiting_input))
async def process_input_non_text(message: Message) -> None:
    await message.answer("Please send text, or /cancel to abort.")


@router.callback_query()
async def cb_unknown(callback: CallbackQuery) -> None:
    await answer_callback(callback, OUTDATED_ALERT, show_alert=True)
    if callback.message is not None and isinstance(callback.message, Message):
        await strip_keyboard(
            callback.bot, callback.message.chat.id, callback.message.message_id
        )
