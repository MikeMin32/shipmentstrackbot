from __future__ import annotations

import pytest

from utils.dates import coerce_iso_date, extract_date_component, parse_iso_date


def test_parse_iso_date() -> None:
    assert parse_iso_date("2026-09-03").isoformat() == "2026-09-03"
    with pytest.raises(ValueError):
        parse_iso_date("03-09-2026")


def test_legacy_datetime_to_date() -> None:
    assert extract_date_component("2026-08-13T18:00:00Z") == "2026-08-13"
    assert coerce_iso_date("2026-08-13T18:00:00Z") == "2026-08-13"


def test_malformed_edd_is_not_an_iso_date() -> None:
    for value in ("tomorrow", "next Friday", "08/13 maybe", "", "   ", "2026-13-40"):
        assert extract_date_component(value) is None
    with pytest.raises(ValueError):
        coerce_iso_date("tomorrow")
