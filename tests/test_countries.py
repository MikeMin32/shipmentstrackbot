from domain.countries import (
    CODE_INDEX,
    country_code_from_index,
    country_code_to_flag,
    format_country_code,
    format_country_label,
    is_iso_country_code,
    recent_country_items,
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


def test_legacy_location_codes_are_not_flagged() -> None:
    assert should_show_flag("LA") is False
    assert format_country_code("LA") == "LA"
    assert format_country_code("ATL") == "ATL"
    assert format_country_code("DE") == "🇩🇪 DE"


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
