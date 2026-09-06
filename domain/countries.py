"""ISO 3166-1 alpha-2 country reference and flag generation."""

from __future__ import annotations

# Officially assigned ISO 3166-1 alpha-2 codes, sorted by English short name.
COUNTRIES: tuple[tuple[str, str], ...] = (
    ("AF", "Afghanistan"),
    ("AL", "Albania"),
    ("DZ", "Algeria"),
    ("AD", "Andorra"),
    ("AO", "Angola"),
    ("AR", "Argentina"),
    ("AM", "Armenia"),
    ("AU", "Australia"),
    ("AT", "Austria"),
    ("AZ", "Azerbaijan"),
    ("BS", "Bahamas"),
    ("BH", "Bahrain"),
    ("BD", "Bangladesh"),
    ("BY", "Belarus"),
    ("BE", "Belgium"),
    ("BZ", "Belize"),
    ("BJ", "Benin"),
    ("BT", "Bhutan"),
    ("BO", "Bolivia"),
    ("BA", "Bosnia and Herzegovina"),
    ("BW", "Botswana"),
    ("BR", "Brazil"),
    ("BN", "Brunei"),
    ("BG", "Bulgaria"),
    ("BF", "Burkina Faso"),
    ("BI", "Burundi"),
    ("KH", "Cambodia"),
    ("CM", "Cameroon"),
    ("CA", "Canada"),
    ("CV", "Cape Verde"),
    ("CF", "Central African Republic"),
    ("TD", "Chad"),
    ("CL", "Chile"),
    ("CN", "China"),
    ("CO", "Colombia"),
    ("KM", "Comoros"),
    ("CG", "Congo"),
    ("CD", "Congo (DRC)"),
    ("CR", "Costa Rica"),
    ("CI", "Côte d'Ivoire"),
    ("HR", "Croatia"),
    ("CU", "Cuba"),
    ("CY", "Cyprus"),
    ("CZ", "Czechia"),
    ("DK", "Denmark"),
    ("DJ", "Djibouti"),
    ("DO", "Dominican Republic"),
    ("EC", "Ecuador"),
    ("EG", "Egypt"),
    ("SV", "El Salvador"),
    ("GQ", "Equatorial Guinea"),
    ("ER", "Eritrea"),
    ("EE", "Estonia"),
    ("SZ", "Eswatini"),
    ("ET", "Ethiopia"),
    ("FJ", "Fiji"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("GA", "Gabon"),
    ("GM", "Gambia"),
    ("GE", "Georgia"),
    ("DE", "Germany"),
    ("GH", "Ghana"),
    ("GR", "Greece"),
    ("GT", "Guatemala"),
    ("GN", "Guinea"),
    ("GW", "Guinea-Bissau"),
    ("GY", "Guyana"),
    ("HT", "Haiti"),
    ("HN", "Honduras"),
    ("HK", "Hong Kong"),
    ("HU", "Hungary"),
    ("IS", "Iceland"),
    ("IN", "India"),
    ("ID", "Indonesia"),
    ("IR", "Iran"),
    ("IQ", "Iraq"),
    ("IE", "Ireland"),
    ("IL", "Israel"),
    ("IT", "Italy"),
    ("JM", "Jamaica"),
    ("JP", "Japan"),
    ("JO", "Jordan"),
    ("KZ", "Kazakhstan"),
    ("KE", "Kenya"),
    ("KW", "Kuwait"),
    ("KG", "Kyrgyzstan"),
    ("LA", "Laos"),
    ("LV", "Latvia"),
    ("LB", "Lebanon"),
    ("LS", "Lesotho"),
    ("LR", "Liberia"),
    ("LY", "Libya"),
    ("LI", "Liechtenstein"),
    ("LT", "Lithuania"),
    ("LU", "Luxembourg"),
    ("MO", "Macao"),
    ("MG", "Madagascar"),
    ("MW", "Malawi"),
    ("MY", "Malaysia"),
    ("MV", "Maldives"),
    ("ML", "Mali"),
    ("MT", "Malta"),
    ("MR", "Mauritania"),
    ("MU", "Mauritius"),
    ("MX", "Mexico"),
    ("MD", "Moldova"),
    ("MC", "Monaco"),
    ("MN", "Mongolia"),
    ("ME", "Montenegro"),
    ("MA", "Morocco"),
    ("MZ", "Mozambique"),
    ("MM", "Myanmar"),
    ("NA", "Namibia"),
    ("NP", "Nepal"),
    ("NL", "Netherlands"),
    ("NZ", "New Zealand"),
    ("NI", "Nicaragua"),
    ("NE", "Niger"),
    ("NG", "Nigeria"),
    ("KP", "North Korea"),
    ("MK", "North Macedonia"),
    ("NO", "Norway"),
    ("OM", "Oman"),
    ("PK", "Pakistan"),
    ("PS", "Palestine"),
    ("PA", "Panama"),
    ("PG", "Papua New Guinea"),
    ("PY", "Paraguay"),
    ("PE", "Peru"),
    ("PH", "Philippines"),
    ("PL", "Poland"),
    ("PT", "Portugal"),
    ("PR", "Puerto Rico"),
    ("QA", "Qatar"),
    ("RO", "Romania"),
    ("RU", "Russia"),
    ("RW", "Rwanda"),
    ("SA", "Saudi Arabia"),
    ("SN", "Senegal"),
    ("RS", "Serbia"),
    ("SG", "Singapore"),
    ("SK", "Slovakia"),
    ("SI", "Slovenia"),
    ("SO", "Somalia"),
    ("ZA", "South Africa"),
    ("KR", "South Korea"),
    ("SS", "South Sudan"),
    ("ES", "Spain"),
    ("LK", "Sri Lanka"),
    ("SD", "Sudan"),
    ("SR", "Suriname"),
    ("SE", "Sweden"),
    ("CH", "Switzerland"),
    ("SY", "Syria"),
    ("TW", "Taiwan"),
    ("TJ", "Tajikistan"),
    ("TZ", "Tanzania"),
    ("TH", "Thailand"),
    ("TL", "Timor-Leste"),
    ("TG", "Togo"),
    ("TT", "Trinidad and Tobago"),
    ("TN", "Tunisia"),
    ("TR", "Turkey"),
    ("TM", "Turkmenistan"),
    ("UG", "Uganda"),
    ("UA", "Ukraine"),
    ("AE", "United Arab Emirates"),
    ("GB", "United Kingdom"),
    ("US", "United States"),
    ("UY", "Uruguay"),
    ("UZ", "Uzbekistan"),
    ("VA", "Vatican City"),
    ("VE", "Venezuela"),
    ("VN", "Vietnam"),
    ("YE", "Yemen"),
    ("ZM", "Zambia"),
    ("ZW", "Zimbabwe"),
)

# Shipment location abbreviations -> ISO country used only for flag generation.
# Checked before ISO lookup so colliding codes (LA is also Laos) keep the
# project's meaning. Add new aliases here; do not special-case them in UI code.
LOCATION_COUNTRY_ALIASES: dict[str, str] = {
    "LA": "US",
    "ATL": "US",
}

DEFAULT_RECENT_CODES: tuple[str, ...] = ("US", "DE", "CA", "IT", "NL", "AU")

CODE_TO_NAME: dict[str, str] = {code: name for code, name in COUNTRIES}
CODE_INDEX: dict[str, int] = {code: index for index, (code, name) in enumerate(COUNTRIES)}


def normalize_country_code(value: str | None) -> str:
    return (value or "").strip().upper()


def is_iso_country_code(value: str | None) -> bool:
    return normalize_country_code(value) in CODE_TO_NAME


def country_code_to_flag(code: str | None) -> str | None:
    """Return the regional-indicator flag for a two-letter ISO code, or None."""
    raw = normalize_country_code(code)
    if len(raw) != 2 or not raw.isascii() or not raw.isalpha():
        return None
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in raw)


def resolve_country_code(value: str | None) -> str | None:
    """ISO country for flag generation. Preserves the caller's display label.

    Aliases are resolved before ISO codes so LA maps to US, not Laos.
    Unknown values return None (no placeholder flag).
    """
    raw = normalize_country_code(value)
    if not raw:
        return None
    alias = LOCATION_COUNTRY_ALIASES.get(raw)
    if alias:
        return alias
    if is_iso_country_code(raw):
        return raw
    return None


def flag_for_location(value: str | None) -> str | None:
    """Flag emoji for a stored country or location, or None if unresolved."""
    resolved = resolve_country_code(value)
    if not resolved:
        return None
    return country_code_to_flag(resolved)


def should_show_flag(code: str | None) -> bool:
    return flag_for_location(code) is not None


def format_country_code(code: str | None, *, empty: str = "") -> str:
    """Compact list form: '🇩🇪 DE' or '🇺🇸 LA'. Display stays the original label."""
    raw = (code or "").strip()
    if not raw:
        return empty
    flag = flag_for_location(raw)
    if not flag:
        return raw
    return f"{flag} {normalize_country_code(raw)}"


def format_country_label(code: str | None) -> str:
    """Picker form: '🇩🇪 Germany' for ISO. Location aliases are not rewritten."""
    raw = (code or "").strip()
    if not raw:
        return ""
    normalized = normalize_country_code(raw)
    name = CODE_TO_NAME.get(normalized)
    if name:
        # Keep picker ISO names. Aliased codes (LA) stay the country name,
        # without applying the shipment-location flag.
        if normalized in LOCATION_COUNTRY_ALIASES:
            return name
        flag = country_code_to_flag(normalized)
        return f"{flag} {name}" if flag else name
    return format_country_code(raw)


def format_stored_country(code: str | None, *, empty: str = "") -> str:
    """Shipment-facing country/location (Home, details, draft current value)."""
    raw = (code or "").strip()
    if not raw:
        return empty
    if normalize_country_code(raw) in LOCATION_COUNTRY_ALIASES or not is_iso_country_code(raw):
        return format_country_code(raw)
    return format_country_label(raw)


def country_code_from_index(index: int) -> str | None:
    if index < 0 or index >= len(COUNTRIES):
        return None
    return COUNTRIES[index][0]


def country_picker_items() -> list[tuple[int, str]]:
    return [(index, format_country_label(code)) for index, (code, _name) in enumerate(COUNTRIES)]


def recent_country_items(used_codes: list[str], *, limit: int = 6) -> list[tuple[int, str]]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in used_codes:
        code = normalize_country_code(raw)
        if not is_iso_country_code(code) or code in LOCATION_COUNTRY_ALIASES or code in seen:
            continue
        seen.add(code)
        ordered.append(code)
        if len(ordered) >= limit:
            break
    if not ordered:
        ordered = [code for code in DEFAULT_RECENT_CODES if code in CODE_INDEX][:limit]
    return [(CODE_INDEX[code], format_country_label(code)) for code in ordered]


def search_countries(query: str) -> list[tuple[int, str]]:
    needle = query.strip().casefold()
    if not needle:
        return country_picker_items()
    matches: list[tuple[int, str]] = []
    for index, (code, name) in enumerate(COUNTRIES):
        if (
            needle == code.casefold()
            or needle in name.casefold()
            or name.casefold().startswith(needle)
        ):
            matches.append((index, format_country_label(code)))
    return matches
