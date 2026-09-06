from domain.countries import (
    CODE_INDEX,
    LOCATION_COUNTRY_ALIASES,
    country_code_from_index,
    country_code_to_flag,
    flag_for_location,
    format_country_code,
    format_country_label,
    format_stored_country,
    is_iso_country_code,
    recent_country_items,
    resolve_country_code,
    search_countries,
    should_show_flag,
)


def test_country_code_to_flag_from_iso() -> None:
    assert country_code_to_flag("DE") == "🇩🇪"
    assert country_code_to_flag("ca") == "🇨🇦"
    assert country_code_to_flag("US") == "🇺🇸"
    assert country_code_to_flag("IT") == "🇮🇹"
    assert country_code_to_flag("FR") == "🇫🇷"
    assert country_code_to_flag("ATL") is None
    assert country_code_to_flag("") is None
    assert country_code_to_flag("D") is None


def test_resolve_country_code_iso_and_aliases() -> None:
    assert resolve_country_code("DE") == "DE"
    assert resolve_country_code("ca") == "CA"
    assert resolve_country_code("US") == "US"
    assert resolve_country_code("IT") == "IT"
    assert resolve_country_code("LA") == "US"
    assert resolve_country_code("la") == "US"
    assert resolve_country_code("ATL") == "US"
    assert resolve_country_code("atl") == "US"
    assert resolve_country_code("XYZ") is None
    assert resolve_country_code("") is None
    assert resolve_country_code(None) is None


def test_format_country_code_uses_alias_flag_without_duplicate_label() -> None:
    assert format_country_code("DE") == "🇩🇪 DE"
    assert format_country_code("CA") == "🇨🇦 CA"
    assert format_country_code("US") == "🇺🇸 US"
    assert format_country_code("IT") == "🇮🇹 IT"
    assert format_country_code("LA") == "🇺🇸 LA"
    assert format_country_code("ATL") == "🇺🇸 ATL"
    assert format_country_code("XYZ") == "XYZ"
    assert format_country_code("  ") == ""
    assert "🇺🇸 US LA" not in format_country_code("LA")
    assert "🇺🇸 US ATL" not in format_country_code("ATL")
    assert should_show_flag("LA") is True
    assert should_show_flag("ATL") is True
    assert should_show_flag("XYZ") is False
    assert should_show_flag("DE") is True
    assert flag_for_location("LA") == "🇺🇸"
    assert flag_for_location("ATL") == "🇺🇸"
    assert flag_for_location("XYZ") is None
    assert LOCATION_COUNTRY_ALIASES["LA"] == "US"
    assert LOCATION_COUNTRY_ALIASES["ATL"] == "US"


def test_unknown_location_stays_readable_without_placeholder_flag() -> None:
    assert format_country_code("XYZ") == "XYZ"
    assert format_stored_country("XYZ") == "XYZ"
    assert "🏳️" not in format_country_code("XYZ")
    assert "None" not in format_country_code("XYZ")
    assert "??" not in format_country_code("XYZ")


def test_country_picker_keeps_iso_names_for_aliased_codes() -> None:
    assert format_country_label("IT") == "🇮🇹 Italy"
    assert format_country_label("DE") == "🇩🇪 Germany"
    assert format_country_label("LA") == "Laos"
    assert format_country_label("ATL") == "🇺🇸 ATL"
    assert format_stored_country("DE") == "🇩🇪 Germany"
    assert format_stored_country("LA") == "🇺🇸 LA"
    assert format_stored_country("ATL") == "🇺🇸 ATL"


def test_country_search_matches_name_and_code() -> None:
    by_name = search_countries("Germany")
    by_partial = search_countries("German")
    by_code = search_countries("DE")
    assert any(CODE_INDEX["DE"] == index for index, _label in by_name)
    assert any(label == "🇩🇪 Germany" for _index, label in by_partial)
    assert any(CODE_INDEX["DE"] == index for index, _label in by_code)
    assert country_code_from_index(CODE_INDEX["DE"]) == "DE"
    assert is_iso_country_code("nl") is True
    assert is_iso_country_code("ATL") is False


def test_recent_countries_prefer_valid_iso_usage() -> None:
    items = recent_country_items(["ATL", "DE", "LA", "CA", "de"], limit=6)
    codes = [country_code_from_index(index) for index, _label in items]
    assert codes == ["DE", "CA"]
    assert all("🇩🇪" in label or "🇨🇦" in label for _index, label in items)
    fallback = recent_country_items(["ATL", "LA"], limit=6)
    assert country_code_from_index(fallback[0][0]) == "US"
    assert format_country_label("IT") == "🇮🇹 Italy"
