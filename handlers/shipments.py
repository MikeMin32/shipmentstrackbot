"""FSM text handlers for creating, searching, and editing shipments."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database.repository import ShipmentRepository
from handlers.common import details_text
from keyboards.inline import (
    main_menu_keyboard,
    search_results_keyboard,
    shipment_details_keyboard,
    status_picker_keyboard,
)
from states.shipment import ShipmentStates
from utils.formatting import esc, format_search_results
from utils.timefmt import (
    INVALID_UTC_DATETIME_MESSAGE,
    format_utc_display,
    parse_utc_datetime,
    to_store,
)

router = Router(name="shipments")

MAX_COUNTRY_LEN = 40
MAX_CLONE_LEN = 80
MAX_NOTE_LEN = 500


@router.message(Command("cancel"))
async def cancel_fsm(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Nothing to cancel.", reply_markup=main_menu_keyboard())
        return
    await state.clear()
    await message.answer("Cancelled.", reply_markup=main_menu_keyboard())


@router.message(ShipmentStates.waiting_country, F.text)
async def process_country(message: Message, state: FSMContext) -> None:
    country = (message.text or "").strip()
    if not country or country.startswith("/"):
        await message.answer(
            "Enter a country / location code (e.g. DE, CA, ATL), or /cancel."
        )
        return
    if len(country) > MAX_COUNTRY_LEN:
        await message.answer(
            f"Too long (max {MAX_COUNTRY_LEN}). Try again or /cancel."
        )
        return

    await state.update_data(pending_country=country)
    await state.set_state(ShipmentStates.waiting_clone)
    await message.answer(
        f"Country: <b>{esc(country)}</b>\n\n"
        "Enter clone name.\n"
        "Example: <code>Oner</code>\n\n"
        "Send /cancel to abort."
    )


@router.message(ShipmentStates.waiting_clone, F.text)
async def process_clone(message: Message, state: FSMContext) -> None:
    clone = (message.text or "").strip()
    if not clone or clone.startswith("/"):
        await message.answer("Enter a clone name (e.g. Oner), or /cancel.")
        return
    if len(clone) > MAX_CLONE_LEN:
        await message.answer(f"Too long (max {MAX_CLONE_LEN}). Try again or /cancel.")
        return

    data = await state.get_data()
    country = data.get("pending_country", "")
    await state.update_data(pending_clone=clone)
    await state.set_state(ShipmentStates.waiting_initial_status)
    await message.answer(
        f"Select status for <b>{esc(country)} : {esc(clone)}</b>:",
        reply_markup=status_picker_keyboard(for_create=True),
    )


@router.message(ShipmentStates.waiting_edd_create, F.text)
async def process_edd_create(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    data = await state.get_data()
    country = (data.get("pending_country") or "").strip()
    clone = (data.get("pending_clone") or "").strip()
    status = data.get("pending_status")
    if not country or not clone or not status:
        await state.clear()
        await message.answer(
            "Session expired. Start again with ➕ Add.",
            reply_markup=main_menu_keyboard(),
        )
        return

    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await message.answer(INVALID_UTC_DATETIME_MESSAGE)
        return

    try:
        edd_dt = parse_utc_datetime(raw)
    except ValueError:
        await message.answer(INVALID_UTC_DATETIME_MESSAGE)
        return

    edd_store = to_store(edd_dt)
    user = message.from_user
    shipment = await repo.create(
        country=country,
        clone_name=clone,
        status=status,
        expected_delivery_date=edd_store,
        created_by=user.id if user else None,
    )
    await state.clear()
    text = await details_text(repo, shipment, notice="✅ Shipment added")
    await message.answer(text, reply_markup=shipment_details_keyboard(shipment["id"]))


@router.message(ShipmentStates.waiting_search, F.text)
async def process_search(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    query = (message.text or "").strip()
    if not query or query.startswith("/"):
        await message.answer("Enter a search query or /cancel.")
        return

    shipments = await repo.search(query)
    await state.clear()
    await message.answer(
        format_search_results(query, shipments),
        reply_markup=search_results_keyboard(shipments),
    )


@router.message(ShipmentStates.waiting_edd, F.text)
async def process_edd(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    data = await state.get_data()
    shipment_id = data.get("shipment_id")
    if not shipment_id:
        await state.clear()
        await message.answer(
            "Session expired. Open the shipment again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await message.answer(INVALID_UTC_DATETIME_MESSAGE)
        return

    try:
        edd_dt = parse_utc_datetime(raw)
    except ValueError:
        await message.answer(INVALID_UTC_DATETIME_MESSAGE)
        return

    shipment = await repo.update_edd(int(shipment_id), to_store(edd_dt))
    await state.clear()
    if shipment is None:
        await message.answer(
            "Shipment not available (maybe archived).",
            reply_markup=main_menu_keyboard(),
        )
        return

    text = await details_text(repo, shipment, notice="✅ EDD updated")
    await message.answer(text, reply_markup=shipment_details_keyboard(shipment["id"]))


@router.message(ShipmentStates.waiting_edit_country, F.text)
async def process_edit_country(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    data = await state.get_data()
    shipment_id = data.get("shipment_id")
    if not shipment_id:
        await state.clear()
        await message.answer(
            "Session expired. Open the shipment again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    country = (message.text or "").strip()
    if not country or country.startswith("/"):
        await message.answer("Enter a country / location code, or /cancel.")
        return
    if len(country) > MAX_COUNTRY_LEN:
        await message.answer(f"Too long (max {MAX_COUNTRY_LEN}). Try again or /cancel.")
        return

    shipment = await repo.update_country(int(shipment_id), country)
    await state.clear()
    if shipment is None:
        await message.answer(
            "Shipment not available (maybe archived).",
            reply_markup=main_menu_keyboard(),
        )
        return

    text = await details_text(repo, shipment, notice="✅ Country updated")
    await message.answer(text, reply_markup=shipment_details_keyboard(shipment["id"]))


@router.message(ShipmentStates.waiting_edit_clone, F.text)
async def process_edit_clone(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    data = await state.get_data()
    shipment_id = data.get("shipment_id")
    if not shipment_id:
        await state.clear()
        await message.answer(
            "Session expired. Open the shipment again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    clone = (message.text or "").strip()
    if not clone or clone.startswith("/"):
        await message.answer("Enter a clone name, or /cancel.")
        return
    if len(clone) > MAX_CLONE_LEN:
        await message.answer(f"Too long (max {MAX_CLONE_LEN}). Try again or /cancel.")
        return

    shipment = await repo.update_clone_name(int(shipment_id), clone)
    await state.clear()
    if shipment is None:
        await message.answer(
            "Shipment not available (maybe archived).",
            reply_markup=main_menu_keyboard(),
        )
        return

    text = await details_text(repo, shipment, notice="✅ Clone name updated")
    await message.answer(text, reply_markup=shipment_details_keyboard(shipment["id"]))


@router.message(ShipmentStates.waiting_note, F.text)
async def process_note(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    data = await state.get_data()
    shipment_id = data.get("shipment_id")
    if not shipment_id:
        await state.clear()
        await message.answer(
            "Session expired. Open the shipment again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    raw = (message.text or "").strip()
    if raw.startswith("/") and raw != "-":
        await message.answer("Enter a note, '-' to clear, or /cancel.")
        return

    note = None if raw == "-" else raw
    if note is not None and len(note) > MAX_NOTE_LEN:
        await message.answer(
            f"Note is too long (max {MAX_NOTE_LEN} characters). Try again or /cancel."
        )
        return

    shipment = await repo.update_note(int(shipment_id), note)
    await state.clear()
    if shipment is None:
        await message.answer(
            "Shipment not available (maybe archived).",
            reply_markup=main_menu_keyboard(),
        )
        return

    text = await details_text(repo, shipment, notice="✅ Note updated")
    await message.answer(text, reply_markup=shipment_details_keyboard(shipment["id"]))


@router.message(ShipmentStates.waiting_reminder, F.text)
async def process_reminder(
    message: Message,
    state: FSMContext,
    repo: ShipmentRepository,
) -> None:
    data = await state.get_data()
    shipment_id = data.get("shipment_id")
    if not shipment_id:
        await state.clear()
        await message.answer(
            "Session expired. Open the shipment again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await message.answer(INVALID_UTC_DATETIME_MESSAGE)
        return

    try:
        remind_at = parse_utc_datetime(raw)
    except ValueError:
        await message.answer(INVALID_UTC_DATETIME_MESSAGE)
        return

    user = message.from_user
    try:
        reminder = await repo.set_reminder(
            int(shipment_id),
            remind_at,
            created_by=user.id if user else None,
        )
    except ValueError:
        await state.clear()
        await message.answer(
            "Shipment not available (maybe archived).",
            reply_markup=main_menu_keyboard(),
        )
        return

    shipment = await repo.get_by_id(int(shipment_id))
    await state.clear()
    if shipment is None:
        await message.answer("Shipment not found.", reply_markup=main_menu_keyboard())
        return

    when = format_utc_display(reminder["remind_at"])
    text = await details_text(
        repo,
        shipment,
        notice=f"✅ Reminder set for {esc(when)}",
    )
    await message.answer(text, reply_markup=shipment_details_keyboard(shipment["id"]))


@router.message(ShipmentStates.waiting_initial_status)
async def waiting_status_click(message: Message) -> None:
    await message.answer(
        "Please choose a status with the buttons above, or send /cancel."
    )


@router.message(ShipmentStates.waiting_country)
@router.message(ShipmentStates.waiting_clone)
@router.message(ShipmentStates.waiting_edd_create)
@router.message(ShipmentStates.waiting_search)
@router.message(ShipmentStates.waiting_edd)
@router.message(ShipmentStates.waiting_note)
@router.message(ShipmentStates.waiting_edit_country)
@router.message(ShipmentStates.waiting_edit_clone)
@router.message(ShipmentStates.waiting_reminder)
async def unexpected_fsm_input(message: Message) -> None:
    await message.answer("Please send text, or /cancel to abort.")
