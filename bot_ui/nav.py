"""Lightweight in-memory navigation stack for workspace Back behavior."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext

HOME_FRAME: dict[str, Any] = {"v": "home", "p": 0}


async def get_nav(state: FSMContext) -> list[dict[str, Any]]:
    data = await state.get_data()
    nav = data.get("nav")
    if not isinstance(nav, list) or not nav:
        return [dict(HOME_FRAME)]
    return list(nav)


async def set_nav(state: FSMContext, nav: list[dict[str, Any]]) -> None:
    await state.update_data(nav=nav)


async def current_frame(state: FSMContext) -> dict[str, Any]:
    nav = await get_nav(state)
    return dict(nav[-1])


async def push(state: FSMContext, frame: dict[str, Any]) -> None:
    nav = await get_nav(state)
    if nav and nav[-1] == frame:
        return
    nav.append(frame)
    await set_nav(state, nav)


async def replace_top(state: FSMContext, frame: dict[str, Any]) -> None:
    nav = await get_nav(state)
    if nav:
        nav[-1] = frame
    else:
        nav = [frame]
    await set_nav(state, nav)


async def pop(state: FSMContext) -> dict[str, Any]:
    nav = await get_nav(state)
    if len(nav) > 1:
        nav.pop()
    else:
        nav = [dict(HOME_FRAME)]
    await set_nav(state, nav)
    return dict(nav[-1])


async def reset_home(state: FSMContext) -> None:
    await set_nav(state, [dict(HOME_FRAME)])


async def goto(state: FSMContext, *frames: dict[str, Any]) -> None:
    stack = [dict(frame) for frame in frames] or [dict(HOME_FRAME)]
    await set_nav(state, stack)
