"""Fictional deadlines only: no network, source pages, or hand-label edits."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_validate_gold import (
    _base,
    _errors_for,
    _rolling_with_date,
    _time_without_timezone,
    ambiguous_example,
    validate_gold,
)

from scholarscope.deadlines import compare, ordered, resolve
from scholarscope.schema import TZ_PATTERN, Deadline, from_gold_label, timezone_info


def deadline(**changes: Any) -> Deadline:
    data = {
        "label": "Fictional deadline",
        "type": "application",
        "cycle_year": 2027,
        "date": "2027-01-20",
        "time": "12:00",
        "timezone": "UTC",
        "rolling": False,
        "status": "present",
        "evidence": [{"quote": "Fictional notice"}],
    }
    return Deadline.model_validate({**data, **changes})


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"rolling": True}, "rolling deadline must have date null"),
        ({"date": None}, "non-rolling deadline needs a date"),
        ({"status": "ambiguous"}, "ambiguous deadline must have date null"),
        ({"timezone": None}, "timezone must be set"),
        ({"time": None}, "timezone set without a time"),
        ({"evidence": []}, "evidence quote"),
        ({"status": "ambiguous", "date": None, "evidence": []}, "evidence quote"),
        ({"time": "24:00"}, "pattern"),
        ({"time": "1:00"}, "pattern"),
        ({"timezone": "UTC+25:00"}, "timezone"),
        ({"timezone": "UTC+04:60"}, "timezone"),
        ({"timezone": "Area/Not_A_Zone"}, "timezone"),
        ({"timezone": " utc "}, "timezone"),
    ],
)
def test_rejects_invalid_deadlines(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        deadline(**changes)


@pytest.mark.parametrize(
    "zone",
    [
        "unknown",
        "UTC",
        "UTC+00:00",
        "UTC-00:00",
        "UTC+05:30",
        "UTC-23:59",
        "UTC+23:59",
        "Europe/Amsterdam",
        "Etc/GMT+5",
        "CET",
    ],
)
def test_shared_timezone_validation(zone: str) -> None:
    assert TZ_PATTERN.fullmatch(zone)
    assert deadline(timezone=zone).timezone == zone
    errors: list[str] = []
    validate_gold.check_deadline(0, deadline(timezone=zone).model_dump(), errors)
    assert errors == []
    assert validate_gold.TZ_PATTERN is TZ_PATTERN
    assert (timezone_info(zone) is None) == (zone == "unknown")


@pytest.mark.parametrize("zone", ["UTC+25:00", "UTC+14:60", "UTC-24:00", "Europe/Fake", ""])
def test_bad_timezones_rejected_by_both_validators(zone: str) -> None:
    data = {**deadline().model_dump(), "timezone": zone}
    errors: list[str] = []
    validate_gold.check_deadline(0, data, errors)
    assert any("timezone" in error for error in errors)
    with pytest.raises(ValidationError):
        Deadline.model_validate(data)


@pytest.mark.parametrize(
    "zone, hour, minute, day",
    [
        ("UTC", 12, 0, 20),
        ("UTC+05:30", 6, 30, 20),
        ("UTC-04:00", 16, 0, 20),
        ("UTC+23:59", 12, 1, 19),
        ("Etc/GMT+5", 17, 0, 20),
    ],
)
def test_resolve_offsets_and_iana(zone: str, hour: int, minute: int, day: int) -> None:
    original = deadline(timezone=zone)
    before = original.model_dump()
    result = resolve(original)
    assert result.precision == "datetime"
    assert result.instant_utc == datetime(2027, 1, day, hour, minute, tzinfo=UTC)
    assert result.local_date == date(2027, 1, 20)
    assert original.model_dump() == before
    assert not original.usable_for_logic


@pytest.mark.parametrize("day, expected_hour", [(27, 11), (29, 10)])
def test_before_and_after_dst(day: int, expected_hour: int) -> None:
    result = resolve(deadline(date=f"2027-03-{day}", timezone="Europe/Amsterdam"))
    assert result.instant_utc == datetime(2027, 3, day, expected_hour, tzinfo=UTC)


@pytest.mark.parametrize(
    "day, hour, word",
    [
        ("2027-03-28", 1, "nonexistent"),
        ("2027-10-31", 0, "ambiguous"),
    ],
)
def test_dst_gap_and_overlap_use_fold_zero(day: str, hour: int, word: str) -> None:
    result = resolve(deadline(date=day, time="02:30", timezone="Europe/Amsterdam"))
    assert result.precision == "datetime"
    assert result.instant_utc == datetime.fromisoformat(day).replace(
        hour=hour, minute=30, tzinfo=UTC
    )
    assert "fold=0" in result.reason and word in result.reason


@pytest.mark.parametrize(
    "changes, precision, reason",
    [
        ({"date": None, "rolling": True, "time": None, "timezone": None}, "unresolved", "rolling"),
        (
            {"date": None, "status": "ambiguous", "time": None, "timezone": None},
            "unresolved",
            "ambiguous",
        ),
        ({"time": None, "timezone": None}, "date", "no time invented"),
        ({"timezone": "unknown"}, "date", "timezone unknown"),
    ],
)
def test_resolution_precision(changes: dict[str, Any], precision: str, reason: str) -> None:
    result = resolve(deadline(**changes))
    assert result.precision == precision and reason in result.reason
    assert result.instant_utc is None
    assert result.local_date == (date(2027, 1, 20) if precision == "date" else None)


def test_does_not_infer_cycle_or_year() -> None:
    record = deadline(date="2024-01-20", cycle_year=2027)
    assert resolve(record).local_date == date(2024, 1, 20)
    assert record.cycle_year == 2027


@pytest.mark.parametrize(
    "verification, usable", [("not_checked", False), ("unverified", False), ("verified", True)]
)
def test_resolution_does_not_promote_verification(verification: str, usable: bool) -> None:
    item = deadline(verification=verification)
    assert item.usable_for_logic is usable
    assert resolve(item).precision == "datetime"
    assert item.verification == verification
    assert item.evidence[0].quote == "Fictional notice"
    assert item.date == "2027-01-20"
    assert Deadline.model_validate_json(item.model_dump_json()) == item
    ambiguous = deadline(status="ambiguous", date=None, verification=verification)
    assert not ambiguous.usable_for_logic


@pytest.mark.parametrize("verification", ["verified", "unverified", "not_checked"])
def test_all_verifications_still_require_evidence(verification: str) -> None:
    with pytest.raises(ValidationError):
        deadline(verification=verification, evidence=[])


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2027, 1, 20, 11, 59, tzinfo=UTC), "upcoming"),
        (datetime(2027, 1, 20, 12, tzinfo=UTC), "upcoming"),
        (datetime(2027, 1, 20, 12, 0, 1, tzinfo=UTC), "past"),
        (datetime(2027, 1, 20, 18, tzinfo=timezone(timedelta(hours=5))), "past"),
    ],
)
def test_compare_instants(now: datetime, expected: str) -> None:
    assert compare(deadline(), now) == expected


@pytest.mark.parametrize("unknown_zone", [False, True])
@pytest.mark.parametrize(
    "utc_now, expected",
    [
        (datetime(2027, 1, 19, 23, tzinfo=UTC), "upcoming"),
        (datetime(2027, 1, 20, 9, 59, 59, 999999, tzinfo=UTC), "upcoming"),
        (datetime(2027, 1, 20, 10, tzinfo=UTC), "unknown"),
        (datetime(2027, 1, 20, 18, tzinfo=UTC), "unknown"),
        (datetime(2027, 1, 21, 11, 59, 59, 999999, tzinfo=UTC), "unknown"),
        (datetime(2027, 1, 21, 12, tzinfo=UTC), "past"),
        (datetime(2027, 1, 21, 12, 0, 1, tzinfo=UTC), "past"),
    ],
)
@pytest.mark.parametrize("offset_hours", [-12, 5, 14])
def test_date_comparison_global_window_is_offset_invariant(
    unknown_zone: bool,
    utc_now: datetime,
    expected: str,
    offset_hours: int,
) -> None:
    item = deadline(timezone="unknown") if unknown_zone else deadline(time=None, timezone=None)
    now = utc_now.astimezone(timezone(timedelta(hours=offset_hours)))
    assert compare(item, now) == expected


@pytest.mark.parametrize("unknown_zone", [False, True])
def test_review_example_does_not_prematurely_expire(unknown_zone: bool) -> None:
    item = (
        deadline(date="2026-10-21", timezone="unknown")
        if unknown_zone
        else deadline(
            date="2026-10-21",
            time=None,
            timezone=None,
        )
    )
    now = datetime(2026, 10, 22, 1, tzinfo=timezone(timedelta(hours=5)))
    assert compare(item, now) == "unknown"


def test_naive_now_rejected_even_for_unresolved() -> None:
    for item in [
        deadline(),
        deadline(rolling=True, date=None),
        deadline(time=None, timezone=None),
        deadline(timezone="unknown"),
    ]:
        with pytest.raises(ValueError, match="timezone-aware"):
            compare(item, datetime(2027, 1, 20))


@pytest.mark.parametrize("optimized", [False, True])
def test_resolve_missing_known_zone_raises_even_when_optimized(optimized: bool) -> None:
    # Exercise the defensive guard with an injected impossible helper outcome.
    # No page data, snapshots or files are involved; -O must not remove the guard.
    code = """
from scholarscope import deadlines
from scholarscope.schema import Deadline
d = Deadline.model_validate({
    'label': 'Fictional', 'type': 'application', 'cycle_year': 2027,
    'date': '2027-01-20', 'time': '12:00', 'timezone': 'UTC',
    'rolling': False, 'status': 'present', 'evidence': [{'quote': 'Fictional notice'}],
})
deadlines.timezone_info = lambda _: None
try:
    deadlines.resolve(d)
except ValueError as exc:
    print(str(exc))
else:
    raise SystemExit('Expected explicit ValueError')
"""
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-B", "-c", code],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "cannot resolve a datetime without a known timezone" in result.stdout


def test_compare_unresolved() -> None:
    assert (
        compare(deadline(rolling=True, date=None), datetime(2027, 1, 20, tzinfo=UTC)) == "unknown"
    )


def test_ordering_retains_unresolved_separately_and_is_stable() -> None:
    rolling = deadline(label="Rolling", rolling=True, date=None)
    ambiguous = deadline(label="Ambiguous", status="ambiguous", date=None)
    dated = deadline(label="Date", time=None, timezone=None)
    timed = deadline(label="Timed")
    earlier = deadline(label="Earlier", timezone="UTC+05:00")
    tied = deadline(label="Tie")
    result = ordered(iter([rolling, timed, ambiguous, tied, dated, earlier]))
    assert isinstance(result, list)
    assert result == [dated, earlier, timed, tied]
    assert result.unresolved == [rolling, ambiguous]
    assert len(result) + len(result.unresolved) == 6
    assert ordered([rolling]).unresolved == [rolling]
    assert ordered([]) == []
    assert all(not d.usable_for_logic for d in result)


def test_ordering_uses_utc_day_for_instants() -> None:
    next_local_day = deadline(date="2027-01-21", time="01:00", timezone="UTC+05:00")
    previous_local_day = deadline(date="2027-01-20", time="23:00", timezone="UTC")
    assert ordered([previous_local_day, next_local_day]) == [next_local_day, previous_local_day]


def test_ordering_keeps_seconds_from_historical_iana_offsets() -> None:
    local = deadline(date="1970-01-20", time="00:00", timezone="Africa/Monrovia")
    utc = deadline(date="1970-01-20", time="00:44", timezone="UTC")
    assert resolve(local).instant_utc == datetime(1970, 1, 20, 0, 44, 30, tzinfo=UTC)
    assert ordered([local, utc]) == [utc, local]


def test_cycles_types_and_ambiguous_quotes_are_preserved() -> None:
    gold = ambiguous_example()
    later = {**gold["deadlines"][0], "cycle_year": 2028, "date": "2028-01-15"}
    gold["deadlines"].append(later)
    record = from_gold_label(gold)
    assert [d.type for d in record.deadlines[:2]] == ["application", "recommender"]
    assert record.deadlines[0].cycle_year == 2027 and record.deadlines[-1].cycle_year == 2028
    assert record.deadlines[2].date is None
    assert len(record.deadlines[2].evidence) == 2
    assert "Candidates" in (record.deadlines[2].notes or "")
    assert all(d.verification == "not_checked" for d in record.deadlines)


@pytest.mark.parametrize("field", ["type", "cycle_year", "date", "time", "timezone", "label"])
def test_duplicate_key_includes_each_decided_component(field: str) -> None:
    base = _base()
    first = base["deadlines"][0]
    changes = {
        "type": "document",
        "cycle_year": 2028,
        "date": "2027-01-16",
        "time": "23:58",
        "timezone": "unknown",
        "label": "Other notice",
    }
    base["deadlines"] = [first, {**first, field: changes[field]}]
    assert len(from_gold_label(base).deadlines) == 2


def test_exact_duplicates_rejected_even_if_quotes_differ() -> None:
    gold = _base()
    first = gold["deadlines"][0]
    gold["deadlines"] = [first, {**first, "evidence": [{"quote": "Another fictional quote"}]}]
    with pytest.raises(ValidationError, match="exact duplicate deadline"):
        from_gold_label(gold)


@pytest.mark.parametrize("verification", ["verified", "unverified"])
def test_gold_converter_resets_deadline_verification(verification: str) -> None:
    gold = _base()
    for item in gold["deadlines"]:
        item["verification"] = verification
    assert all(d.verification == "not_checked" for d in from_gold_label(gold).deadlines)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (_time_without_timezone, "timezone must be set"),
        (_rolling_with_date, "rolling deadline must have date null"),
    ],
)
def test_existing_gold_mutation_parity(mutate: Any, message: str, tmp_path: Path) -> None:
    label = _base()
    mutate(label)
    assert any(message in e for e in _errors_for(label, tmp_path))
    with pytest.raises(ValidationError, match=message):
        Deadline.model_validate(label["deadlines"][0])


def test_approved_ambiguous_case_parity(tmp_path: Path) -> None:
    gold = ambiguous_example()
    assert _errors_for(gold, tmp_path) == []
    assert len(from_gold_label(gold).deadlines[-1].evidence) == 2
    cases: list[tuple[dict[str, Any], str]] = [
        ({"date": "2027-01-20"}, "ambiguous deadline must have date null"),
        ({"evidence": []}, "evidence quote"),
    ]
    for changes, message in cases:
        invalid = {**gold["deadlines"][-1], **changes}
        errors: list[str] = []
        validate_gold.check_deadline(0, invalid, errors)
        assert any(message in e for e in errors)
        with pytest.raises(ValidationError, match=message):
            Deadline.model_validate(invalid)


def test_fictional_example_deadlines_load() -> None:
    assert len(from_gold_label(_base()).deadlines) == 2
