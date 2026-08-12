"""FSM states for multi-step shipment input."""

from aiogram.fsm.state import State, StatesGroup


class ShipmentStates(StatesGroup):
    waiting_country = State()
    waiting_clone = State()
    waiting_initial_status = State()
    waiting_edd_create = State()
    waiting_search = State()
    waiting_edd = State()
    waiting_note = State()
    waiting_edit_country = State()
    waiting_edit_clone = State()
    waiting_reminder = State()
