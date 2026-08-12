"""Inline callback handlers for menus and shipment actions."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database.repository import ShipmentRepository
from handlers.common import details_text
from handlers.start import MAIN_MENU_TEXT
from keyboards.inline import (
    MenuCB,
    ShipmentCB,
    StatusCB,
    active_summary_keyboard,
    archive_confirm_keyboard,
    by_status_keyboard,
    main_menu_keyboard,
    reminder_menu_keyboard,
    select_shipment_keyboard,
    shipment_details_keyboard,
    status_picker_keyboard,
    status_shipments_keyboard,
)
from states.shipment import ShipmentStates
from utils.formatting import (
    DEFAULT_STATUS,
    STATUSES,
    esc,
    format_active_list,
    format_reminder_menu,
    format_status_list,
    format_status_shipments,
    shipment_title,
    status_label,
)
from utils.telegram import answer_callback, safe_edit_text
from utils.timefmt import UTC_INPUT_FORMAT, format_utc_display

router = Router(name="callbacks")


async def _show_active(callback: CallbackQuery, repo: ShipmentRepository) -> None:
    shipments = await repo.list_active()
    await safe_edit_text(
        callback.message,
        format_active_list(shipments),
        reply_markup=active_summary_keyboard(),
    )


async def _show_details(
    callback: CallbackQuery,
    repo: ShipmentRepository,
    shipment_id: int,
    *,
    notice: str | None = None,
) -> None:
    shipment = await repo.get_by_id(shipment_id)
    if shipment is None:
        await answer_callback(callback, "Shipment not found.", show_alert=True)
        await _show_active(callback, repo)
        return
    if shipment["archived"]:
        await answer_callback(callback, "This shipment is archived.", show_alert=True)
        await _show_active(callback, repo)
        return

    text = await details_text(repo, shipment, notice=notice)
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=shipment_details_keyboard(shipment_id),
    )


@router.callback_query(MenuCB.filter(F.action == "home"))
async def menu_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        MAIN_MENU_TEXT,
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(MenuCB.filter(F.action == "active"))
async def menu_active(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    await answer_callback(callback)
    await _show_active(callback, repo)


@router.callback_query(MenuCB.filter(F.action == "select"))
async def menu_select(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    shipments = await repo.list_active()
    await answer_callback(callback)
    if not shipments:
        await safe_edit_text(
            callback.message,
            format_active_list(shipments),
            reply_markup=active_summary_keyboard(),
        )
        return

    await safe_edit_text(
        callback.message,
        "<b>🔎 Select Shipment</b>\n\nChoose a shipment:",
        reply_markup=select_shipment_keyboard(shipments),
    )


@router.callback_query(MenuCB.filter(F.action == "add"))
async def menu_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ShipmentStates.waiting_country)
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        "Enter country / location code.\n\n"
        "Examples: <code>DE</code>, <code>CA</code>, <code>LA</code>, <code>ATL</code>\n\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(MenuCB.filter(F.action == "search"))
async def menu_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ShipmentStates.waiting_search)
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        "Enter shipment name or part of the name.\n\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(MenuCB.filter(F.action == "by_status"))
async def menu_by_status(
    callback: CallbackQuery,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    counts = await repo.count_by_status()
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        format_status_list(counts),
        reply_markup=by_status_keyboard(counts),
    )


@router.callback_query(StatusCB.filter(F.action == "list"))
async def status_list(
    callback: CallbackQuery,
    callback_data: StatusCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    status = callback_data.status
    if status not in STATUSES:
        await answer_callback(callback, "Unknown status.", show_alert=True)
        return

    shipments = await repo.list_by_status(status)
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        format_status_shipments(status, shipments),
        reply_markup=status_shipments_keyboard(status, shipments),
    )


@router.callback_query(ShipmentCB.filter(F.action == "view"))
async def shipment_view(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    await answer_callback(callback)
    await _show_details(callback, repo, callback_data.shipment_id)


@router.callback_query(ShipmentCB.filter(F.action == "status"))
async def shipment_change_status(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"<b>{esc(shipment_title(shipment))}</b>\n\n"
        f"Current: {status_label(shipment['status'])}\n\n"
        "Select new status:",
        reply_markup=status_picker_keyboard(shipment_id=shipment["id"]),
    )


@router.callback_query(ShipmentCB.filter(F.action == "set_status"))
async def shipment_set_status(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    repo: ShipmentRepository,
) -> None:
    new_status = callback_data.value
    if new_status not in STATUSES:
        await answer_callback(callback, "Unknown status.", show_alert=True)
        return

    user = callback.from_user
    shipment = await repo.update_status(
        callback_data.shipment_id,
        new_status,
        changed_by=user.id if user else None,
    )
    if shipment is None:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await answer_callback(callback, "Status updated")
    await _show_details(callback, repo, shipment["id"], notice="✅ Status updated")


@router.callback_query(ShipmentCB.filter(F.action == "cancel_status"))
async def shipment_cancel_status(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    repo: ShipmentRepository,
) -> None:
    await answer_callback(callback)
    await _show_details(callback, repo, callback_data.shipment_id)


@router.callback_query(ShipmentCB.filter(F.action == "create_status"))
async def shipment_create_status_chosen(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    country = (data.get("pending_country") or "").strip()
    clone = (data.get("pending_clone") or "").strip()
    if not country or not clone:
        await state.clear()
        await answer_callback(
            callback,
            "Session expired. Start again with ➕ Add.",
            show_alert=True,
        )
        await safe_edit_text(
            callback.message,
            MAIN_MENU_TEXT,
            reply_markup=main_menu_keyboard(),
        )
        return

    status = callback_data.value or DEFAULT_STATUS
    if status not in STATUSES:
        await answer_callback(callback, "Unknown status.", show_alert=True)
        return

    await state.update_data(pending_status=status)
    await state.set_state(ShipmentStates.waiting_edd_create)
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"<b>{esc(country)} : {esc(clone)}</b>\n"
        f"Status: {status_label(status)}\n\n"
        "Enter expected delivery date (EDD) in UTC.\n\n"
        "Format:\n"
        f"<code>{UTC_INPUT_FORMAT}</code>\n\n"
        "Example:\n"
        "<code>2026-08-09 18:00</code>\n\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(ShipmentCB.filter(F.action == "edit_country"))
async def shipment_edit_country(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await state.set_state(ShipmentStates.waiting_edit_country)
    await state.update_data(shipment_id=shipment["id"])
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"<b>{esc(shipment_title(shipment))}</b>\n\n"
        f"Current country: {esc(shipment.get('country') or '—')}\n\n"
        "Enter new country/location code.\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(ShipmentCB.filter(F.action == "edit_clone"))
async def shipment_edit_clone(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await state.set_state(ShipmentStates.waiting_edit_clone)
    await state.update_data(shipment_id=shipment["id"])
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"<b>{esc(shipment_title(shipment))}</b>\n\n"
        f"Current clone: {esc(shipment.get('clone_name') or '—')}\n\n"
        "Enter new clone name.\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(ShipmentCB.filter(F.action == "edd"))
async def shipment_edd(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    current = format_utc_display(
        shipment.get("expected_delivery_date") or shipment.get("expected_date")
    )
    await state.set_state(ShipmentStates.waiting_edd)
    await state.update_data(shipment_id=shipment["id"])
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"<b>{esc(shipment_title(shipment))}</b>\n\n"
        f"Current EDD: {esc(current)}\n\n"
        "Enter new EDD in UTC.\n\n"
        "Format:\n"
        f"<code>{UTC_INPUT_FORMAT}</code>\n\n"
        "Example:\n"
        "<code>2026-08-09 18:00</code>\n\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(ShipmentCB.filter(F.action == "note"))
async def shipment_note(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await state.set_state(ShipmentStates.waiting_note)
    await state.update_data(shipment_id=shipment["id"])
    current = shipment.get("note") or "—"
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"<b>{esc(shipment_title(shipment))}</b>\n\n"
        f"Current note: {esc(current)}\n\n"
        "Send a short note.\n"
        "Send <code>-</code> to remove it.\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(ShipmentCB.filter(F.action == "reminder"))
async def shipment_reminder_menu(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    reminder = await repo.get_active_reminder(shipment["id"])
    reminder_text = (
        format_utc_display(reminder["remind_at"]) if reminder else None
    )
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        format_reminder_menu(shipment, reminder_text),
        reply_markup=reminder_menu_keyboard(
            shipment["id"],
            has_reminder=reminder is not None,
        ),
    )


@router.callback_query(ShipmentCB.filter(F.action == "rem_set"))
async def shipment_reminder_set(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await state.set_state(ShipmentStates.waiting_reminder)
    await state.update_data(shipment_id=shipment["id"])
    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f"⏰ Reminder for <b>{esc(shipment_title(shipment))}</b>\n\n"
        "Enter reminder date/time in UTC.\n\n"
        "Format:\n"
        f"<code>{UTC_INPUT_FORMAT}</code>\n\n"
        "Example:\n"
        "<code>2026-08-09 15:00</code>\n\n"
        "Send /cancel to abort.",
        reply_markup=None,
    )


@router.callback_query(ShipmentCB.filter(F.action == "rem_remove"))
async def shipment_reminder_remove(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    await state.clear()
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await repo.cancel_active_reminders(shipment["id"])
    await repo.db.connection.commit()
    await answer_callback(callback, "Reminder removed")
    await _show_details(callback, repo, shipment["id"], notice="✅ Reminder removed",
    )


@router.callback_query(ShipmentCB.filter(F.action.in_({"archive", "complete"})))
async def shipment_archive_prompt(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    repo: ShipmentRepository,
) -> None:
    shipment = await repo.get_by_id(callback_data.shipment_id)
    if shipment is None or shipment["archived"]:
        await answer_callback(callback, "Shipment not available.", show_alert=True)
        await _show_active(callback, repo)
        return

    await answer_callback(callback)
    await safe_edit_text(
        callback.message,
        f'Archive "<b>{esc(shipment_title(shipment))}</b>"?',
        reply_markup=archive_confirm_keyboard(shipment["id"]),
    )


@router.callback_query(ShipmentCB.filter(F.action == "archive_yes"))
async def shipment_archive_yes(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    repo: ShipmentRepository,
) -> None:
    user = callback.from_user
    shipment = await repo.archive(
        callback_data.shipment_id,
        changed_by=user.id if user else None,
    )
    if shipment is None:
        await answer_callback(callback, "Shipment not found.", show_alert=True)
        await _show_active(callback, repo)
        return

    await answer_callback(callback, "Archived")
    shipments = await repo.list_active()
    text = (
        f'✅ Archived "<b>{esc(shipment_title(shipment))}</b>"\n\n'
        + format_active_list(shipments)
    )
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=active_summary_keyboard(),
    )


@router.callback_query(ShipmentCB.filter(F.action == "archive_no"))
async def shipment_archive_no(
    callback: CallbackQuery,
    callback_data: ShipmentCB,
    repo: ShipmentRepository,
) -> None:
    await answer_callback(callback)
    await _show_details(callback, repo, callback_data.shipment_id)
