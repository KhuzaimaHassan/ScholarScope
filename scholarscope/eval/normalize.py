"""Symmetric value normalization from guide 07 §5; no inference or fuzzy match.

Unknown/underspecified dates, zones, currencies and GPA scales stay as supplied.
This is NOT the verifier's more permissive quote-format normalization.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_MONTHS = {
    name: i
    for i, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
}
_ZONES = {
    "JST": "Asia/Tokyo",
    "Beijing time": "Asia/Shanghai",
    "CET": "UTC+01:00",
    "CEST": "UTC+02:00",
}
_DEGREES = {
    "master": "master",
    "msc": "master",
    "ma": "master",
    "laurea magistrale": "master",
    "phd": "phd",
    "doctoral": "phd",
}


def normalize_date(value: str) -> str:
    """Accept ISO or explicit day + English month + four-digit year, never guess."""
    text = " ".join(value.split())
    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+) (\d{4})", text)
    reverse = re.fullmatch(r"([A-Za-z]+) (\d{1,2}),? (\d{4})", text)
    try:
        if match and match[2].lower() in _MONTHS:
            return date(int(match[3]), _MONTHS[match[2].lower()], int(match[1])).isoformat()
        if reverse and reverse[1].lower() in _MONTHS:
            return date(int(reverse[3]), _MONTHS[reverse[1].lower()], int(reverse[2])).isoformat()
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return text


def normalize_value(value: Any, *, field: str = "") -> Any:
    """Apply the same conservative transform to gold and prediction.

    Collection-valued claims are order-independent multisets (duplicates kept).
    Ignore only missing/null optional object properties, not stated wording.
    GPA/money numeric values are never rescaled or converted; 3 and 3.0 agree.
    """
    if isinstance(value, str):
        text = " ".join(value.split())
        if field == "date":
            return normalize_date(text)
        if field == "timezone":
            return _ZONES.get(text, text)
        if field == "degree_levels":
            return _DEGREES.get(text.lower(), text)
        if field == "time":
            match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(AM|PM)", text, re.IGNORECASE)
            if match and 1 <= int(match[1]) <= 12 and int(match[2]) < 60:
                hour = int(match[1]) % 12 + (12 if match[3].upper() == "PM" else 0)
                return f"{hour:02d}:{int(match[2]):02d}"
        return text
    if isinstance(value, dict):
        return {
            key: normalize_value(item, field=key)
            for key, item in sorted(value.items())
            if item is not None
        }
    if isinstance(value, (list, tuple)):
        import json

        return sorted(
            (normalize_value(item, field=field) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
        )
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical(value: Any, *, field: str = "") -> str:
    import json

    return json.dumps(
        normalize_value(value, field=field),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
