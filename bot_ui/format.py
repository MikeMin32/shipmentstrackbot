"""HTML formatting for the Telegram workspace (escape all dynamic values)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from domain.countries import (
    flag_for_location,
    format_country_code,
    format_stored_country,
)
from domain.status import (
    home_section_label,
    status_emoji,
    status_line as domain_status_line,
)
from utils.dates import extract_date_component
from utils.timefmt import try_parse_stored

WEEKDAYS_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

MONTHS_ABBR = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

LABEL_WIDTH = 14


def esc(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value))


def display_title(shipment: dict[str, Any]) -> str:
    """Name first, country second. Legacy rows fall back to account, then clone."""
    name = (shipment.get("name") or "").strip()
    account = (shipment.get("account_name") or "").strip()
    clone = (shipment.get("clone_name") or "").strip()
    primary = name or account or clone
    country = format_country_code(shipment.get("country"))
    if primary and country:
        return f"{primary} · {country}"
    if primary:
        return primary
    if country:
        return country
    legacy = (shipment.get("display_name") or "").strip()
    if legacy:
        return legacy.replace(" : ", " · ").replace(":", " ·")
    return f"#{shipment.get('id', '?')}"


def compact_title(shipment: dict[str, Any]) -> str:
    return display_title(shipment)


def status_dot(status: str) -> str:
    return status_emoji(status)


def status_line(status: str) -> str:
    return domain_status_line(status)


def format_human_date(
    value: str | None,
    *,
    today: date | None = None,
    with_year: bool | None = None,
    empty: str = "—",
) -> str:
    iso = extract_date_component(value)
    if not iso:
        return empty
    parsed = date.fromisoformat(iso)
    include_year = with_year
    if include_year is None:
        ref = today or date.today()
        include_year = parsed.year != ref.year
    month = MONTHS_ABBR[parsed.month - 1]
    day = f"{parsed.day:02d}"
    if include_year:
        return f"{month} {day}, {parsed.year}"
    return f"{month} {day}"


def format_home_date(
    value: str | None,
    *,
    today: date,
) -> str | None:
    """Compact Home date: Today/Tomorrow or weekday + month + day."""
    iso = extract_date_component(value)
    if not iso:
        return None
    parsed = date.fromisoformat(iso)
    month = MONTHS_ABBR[parsed.month - 1]
    day = str(parsed.day)
    if parsed == today:
        return f"Today, {month} {day}"
    if parsed == today + timedelta(days=1):
        return f"Tomorrow, {month} {day}"
    weekday = WEEKDAYS_ABBR[parsed.weekday()]
    return f"{weekday}, {month} {day}"


def format_unit_quantity(value: Any, *, empty: str = "—") -> str:
    text = _unit_quantity_number(value)
    return text if text is not None else empty


def format_unit_quantity_compact(value: Any) -> str | None:
    """Compact notification form, e.g. 5u. None when the value is missing."""
    text = _unit_quantity_number(value)
    if text is None:
        return None
    return f"{text}u"


def _unit_quantity_number(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return f"{number:.3f}".rstrip("0").rstrip(".")




def format_reminder_at(
    value: str | None,
    *,
    tz_name: str = "UTC",
    empty: str = "—",
) -> str:
    dt = try_parse_stored(value)
    if dt is None:
        return empty
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    local = dt.astimezone(tz)
    return f"{format_human_date(local.date().isoformat(), with_year=local.year != datetime.now(tz).year)} · {local.strftime('%H:%M')}"


def _row(label: str, value: str) -> str:
    padded = label.ljust(LABEL_WIDTH)
    return f"{esc(padded)}{value}"


def _dash(value: str | None) -> str:
    text = (value or "").strip()
    return esc(text) if text else "—"


def format_home(
    *,
    page_items: list[dict[str, Any]],
    today: date,
    account_line: str = "",
    page: int = 0,
    pages: int = 1,
    total_active: int | None = None,
    page_size: int = 9,
) -> str:
    active = total_active if total_active is not None else len(page_items)
    lines: list[str] = []
    sections: list[tuple[str, list[tuple[int, dict[str, Any]]]]] = []
    current_status: str | None = None
    current_rows: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(page_items, start=1):
        status = item.get("status") or ""
        if status != current_status:
            if current_status is not None:
                sections.append((current_status, current_rows))
            current_status = status
            current_rows = []
        current_rows.append((index, item))
    if current_status is not None:
        sections.append((current_status, current_rows))

    for section_index, (status, rows) in enumerate(sections):
        if section_index:
            lines.append("")
        emoji = status_emoji(status)
        lines.append(f"{emoji} <b>{esc(home_section_label(status))}</b>")
        for index, item in rows:
            lines.append(_home_item_line(index, item, today))
    if not page_items:
        lines.append("No active shipments.")
    if pages > 1 and page_items:
        start = page * page_size + 1
        end = page * page_size + len(page_items)
        lines.append(f"Showing {start}–{end} of {active}")
    if account_line:
        lines.append("")
        lines.append("👤 <b>ACCOUNTS</b>")
        lines.append(esc(account_line))
    return "\n".join(lines)


def _home_item_line(index: int, item: dict[str, Any], today: date, *, with_status: bool = False) -> str:
    title = display_title(item)
    edd = format_home_date(
        item.get("expected_delivery_date") or item.get("expected_date"),
        today=today,
    )
    prefix = f"{status_dot(item.get('status') or '')} " if with_status else ""
    if edd:
        return f"{index}. {prefix}{esc(title)} — {edd}"
    return f"{index}. {prefix}{esc(title)}"


def format_account_compact(rows: list[dict[str, Any]], *, limit: int = 3) -> str:
    if not rows:
        return "No accounts yet"
    unassigned = [row for row in rows if row.get("id") is None or row.get("unassigned")]
    named = [row for row in rows if not (row.get("id") is None or row.get("unassigned"))]
    ordered = unassigned + named
    shown = ordered[:limit]
    parts = [f"{row.get('name') or 'No account'} {int(row.get('total') or 0)}" for row in shown]
    extra = len(ordered) - len(shown)
    if extra > 0:
        parts.append(f"+{extra} more")
    return " · ".join(parts)


def format_details(
    shipment: dict[str, Any],
    *,
    reminder_text: str | None,
    today: date,
) -> str:
    sid = shipment.get("id", "?")
    title = esc(display_title(shipment))
    status = shipment.get("status") or ""
    note = shipment.get("note")
    lines = [
        f"<b>📦 #{esc(sid)} · {title}</b>",
        status_line(status),
        "",
        _row("Account", _dash(shipment.get("account_name"))),
        _row("Client Team", _dash(shipment.get("client_team_name"))),
        _row("Unit quantity", format_unit_quantity(shipment.get("unit_quantity"))),
        "",
        _row("Label", format_human_date(shipment.get("label_creation_date"), today=today)),
        _row("Scanned", format_human_date(shipment.get("scanned_in_date"), today=today)),
        _row("Expected", format_human_date(shipment.get("expected_delivery_date") or shipment.get("expected_date"), today=today)),
        _row("Delivered", format_human_date(shipment.get("delivered_date"), today=today)),
        "",
        _row("Reminder", reminder_text or "—"),
        _row("Note", _dash(note) if note else "—"),
    ]
    if shipment.get("archived"):
        lines += ["", "<i>Archived</i>"]
    return "\n".join(lines)


def format_draft(
    draft: dict[str, Any],
    *,
    account_name: str | None,
    team_name: str | None,
    today: date,
) -> str:
    def req(label: str, filled: bool) -> str:
        return f"{label} *" if not filled else label

    country = (draft.get("country") or "").strip()
    name = (draft.get("name") or "").strip()
    country_shown = format_stored_country(country) if country else ""
    lines = [
        "<b>➕ NEW SHIPMENT</b>",
        "",
        _row(req("Account", bool(draft.get("account_id"))), _dash(account_name)),
        _row(req("Name", bool(name)), _dash(name)),
        _row(req("Country", bool(country)), _dash(country_shown)),
        _row("Client Team", _dash(team_name)),
        _row("Unit quantity", format_unit_quantity(draft.get("unit_quantity"))),
        _row("Status", status_line(draft.get("status") or "preparing")),
        "",
        _row("Label", format_human_date(draft.get("label_creation_date"), today=today)),
        _row("Scanned", format_human_date(draft.get("scanned_in_date"), today=today)),
        _row("Expected", format_human_date(draft.get("expected_delivery_date"), today=today)),
        "",
        _row("Note", _dash(draft.get("note"))),
        "",
        "<i>* required</i>",
    ]
    return "\n".join(lines)


def format_picker(
    *,
    title: str,
    current: str | None,
    numbered_items: list[str] | None = None,
    section_label: str | None = None,
) -> str:
    lines = [f"<b>{esc(title)}</b>"]
    if current:
        lines.append(f"Current: {esc(current)}")
    elif not numbered_items:
        lines.append("Current: —")
    if section_label:
        lines.append(section_label)
    if numbered_items:
        lines.extend(numbered_items)
    return "\n".join(lines)


def format_date_field(*, title: str, current: str | None, today: date) -> str:
    shown = format_human_date(current, today=today, with_year=True) if current else "—"
    lines = [f"<b>{esc(title)}</b>"]
    if current:
        lines.append(f"Current: {shown}")
    return "\n".join(lines)


def format_calendar(*, title: str, current: str | None, today: date) -> str:
    shown = format_human_date(current, today=today, with_year=True) if current else "—"
    lines = [f"<b>📅 {esc(title)}</b>"]
    if current:
        lines.append(f"Current: {shown}")
    return "\n".join(lines)


def format_search_prompt() -> str:
    return "<b>🔎 SEARCH</b>\nType shipment ID, name, country, account, or team."


def format_search_results(
    query: str,
    *,
    items: list[dict[str, Any]],
    total: int,
    page: int,
    pages: int,
    today: date,
    page_size: int = 9,
) -> str:
    if total == 0:
        return f"<b>🔎 SEARCH</b>\nNo shipments matching <b>{esc(query)}</b>."
    lines = [f"<b>🔎 SEARCH</b> · {total}", f"Query: {esc(query)}"]
    for index, item in enumerate(items, start=1):
        lines.append(_home_item_line(index, item, today, with_status=True))
    if pages > 1:
        start = page * page_size + 1
        end = page * page_size + len(items)
        lines.append(f"Showing {start}–{end} of {total}")
    return "\n".join(lines)


def format_list(
    *,
    title: str,
    filter_label: str,
    total: int,
    items: list[dict[str, Any]] | None = None,
    page: int = 0,
    pages: int = 1,
    today: date | None = None,
    page_size: int = 9,
) -> str:
    lines = [f"<b>{esc(title)}</b> · {total}", f"Filter: {esc(filter_label)}"]
    if items is not None:
        if not items:
            lines.append("No shipments.")
        elif today is not None:
            for index, item in enumerate(items, start=1):
                lines.append(_home_item_line(index, item, today, with_status=True))
        if pages > 1 and items:
            start = page * page_size + 1
            end = page * page_size + len(items)
            lines.append(f"Showing {start}–{end} of {total}")
    return "\n".join(lines)


def format_accounts(
    rows: list[dict[str, Any]],
    *,
    numbered: bool = False,
    page: int = 0,
    pages: int = 1,
    total: int | None = None,
    page_size: int = 8,
) -> str:
    if not rows and not numbered:
        return "<b>📊 ACCOUNTS</b>\nNo accounts yet."
    lines = ["<b>📊 ACCOUNTS</b>"]
    if not rows:
        lines.append("No accounts yet.")
        return "\n".join(lines)
    for offset, row in enumerate(rows, start=1):
        name = esc(row.get("name") or "No account")
        count_total = int(row.get("total") or 0)
        active = int(row.get("active") or 0)
        prefix = f"{offset}. " if numbered else ""
        lines.append(f"{prefix}{name}    {count_total} total · {active} active")
    count = total if total is not None else len(rows)
    if pages > 1:
        start = page * page_size + 1
        end = page * page_size + len(rows)
        lines.append(f"Showing {start}–{end} of {count}")
    return "\n".join(lines)


def format_history(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
) -> str:
    title = esc(compact_title(shipment))
    lines = [
        "<b>📜 STATUS HISTORY</b>",
        f"#{esc(shipment.get('id'))} · {title}",
        "",
    ]
    if not events:
        lines.append("No history yet.")
        return "\n".join(lines)
    for event in events:
        when = esc(event.get("changed_at") or "—")
        old = event.get("old_status")
        new = event.get("new_status") or ""
        if old:
            change = f"{status_line(old)} → {status_line(new)}"
        else:
            change = f"Created as {status_line(new)}"
        lines.append(when)
        lines.append(esc(change))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_archive_confirm(shipment: dict[str, Any]) -> str:
    return f"Archive #{esc(shipment.get('id'))} · {esc(display_title(shipment))}?"


def format_delivered_confirm(shipment: dict[str, Any]) -> str:
    return f"Mark #{esc(shipment.get('id'))} · {esc(display_title(shipment))} as delivered today?"


def format_reminder(shipment: dict[str, Any], current: str | None) -> str:
    return (
        "<b>⏰ REMINDER</b>\n"
        f"{esc(display_title(shipment))}\n\n"
        f"Current: {current or '—'}"
    )


def format_unit_quantity_prompt(current: Any) -> str:
    return (
        "<b>UNIT QUANTITY</b>\n"
        f"Current: {format_unit_quantity(current)}\n\n"
        "Type the new unit quantity."
    )


def format_edd_reminder_notice(shipment: dict[str, Any], *, hours: int) -> str:
    """Expected Delivery 48h/24h notice. HTML; escape all dynamic values."""
    name = (shipment.get("name") or "").strip()
    if not name:
        name = (shipment.get("account_name") or "").strip() or (shipment.get("clone_name") or "").strip()
    qty = format_unit_quantity_compact(shipment.get("unit_quantity"))
    team = (shipment.get("client_team_name") or "").strip()
    flag = flag_for_location(shipment.get("country"))
    prefix = f"{flag} " if flag else ""

    if name:
        head = f"{prefix}<b>{esc(name)}</b>"
        if qty:
            head = f"{head} <i>{esc(qty)}</i>"
        lead = f"{head} shipment expected delivery"
    elif qty:
        lead = f"{prefix}<i>{esc(qty)}</i> shipment expected delivery"
    else:
        lead = f"{prefix}Shipment expected delivery"

    hours_text = f"<b>{int(hours)} hrs</b>"
    if team:
        return f"{lead} to <b>{esc(team)}</b> in {hours_text}; check tracking"
    return f"{lead} in {hours_text}; check tracking"


def format_note_prompt() -> str:
    return (
        "<b>📝 NOTE</b>\n\n"
        "Type the shipment note.\n"
        "Send <code>-</code> to clear it."
    )


def format_new_account_prompt() -> str:
    return "<b>➕ NEW ACCOUNT</b>\n\nType account name."


def format_new_team_prompt() -> str:
    return "<b>➕ NEW TEAM</b>\n\nType client team name."


def format_name_prompt(current: str | None = None) -> str:
    shown = (current or "").strip() or "—"
    return (
        "<b>✏️ NAME</b>\n"
        f"Current: {esc(shown)}\n\n"
        "Type the shipment name."
    )


def format_new_value_prompt(kind: str) -> str:
    label = "country / location" if kind == "country" else "value"
    return f"<b>➕ NEW {esc(label.upper())}</b>\n\nType the {esc(label)}."


def format_reminder_notice(shipment: dict[str, Any]) -> str:
    title = esc(compact_title(shipment))
    status = status_line(shipment.get("status") or "")
    edd = format_human_date(
        shipment.get("expected_delivery_date") or shipment.get("expected_date"),
        with_year=True,
    )
    return (
        "⏰ <b>Shipment reminder</b>\n\n"
        f"{title}\n"
        f"{esc(status)}\n"
        f"Expected {edd}"
    )


def truncate_button(text: str, limit: int = 64) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
