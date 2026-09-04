"""FSM states for workspace free-text input."""

from aiogram.fsm.state import State, StatesGroup


class WorkspaceStates(StatesGroup):
    waiting_input = State()
