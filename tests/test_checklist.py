"""Fictional records only; no gold fixtures, snapshots, live sites or providers."""

from __future__ import annotations

import ast
import random
import socket
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from scholarscope import checklist as module
from scholarscope.checklist import (
    DEFAULT_POLICY,
    BufferPolicy,
    Checklist,
    ItemKind,
    WarningCode,
    build_checklist,
)
from scholarscope.deadlines import compare
from scholarscope.schema import Deadline, RequirementRecord

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("checklist tests must never connect to a network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def deadline(**changes: Any) -> Deadline:
    return Deadline.model_validate(
        {
            "label": "Fictional deadline",
            "type": "application",
            "cycle_year": 2026,
            "date": "2026-11-30",
            "time": "23:59",
            "timezone": "UTC",
            "rolling": False,
            "status": "present",
            "verification": "verified",
            "evidence": [{"quote": "Fictional date evidence", "passage_id": "p0000-fiction"}],
            **changes,
        }
    )


def claim(value: Any, **changes: Any) -> dict[str, Any]:
    return {
        "status": "present",
        "value": value,
        "verification": "verified",
        "evidence": [{"quote": "Fictional requirement evidence", "locator": "node/p"}],
        **changes,
    }


def record(*deadlines: Deadline, **changes: Any) -> RequirementRecord:
    absent: dict[str, Any] = {"status": "absent", "value": None, "evidence": []}
    fields = {
        key: deepcopy(absent)
        for key in (
            "program_name",
            "institution",
            "degree_levels",
            "funding_coverage",
            "required_documents",
            "recommenders",
            "application_link",
        )
    }
    return RequirementRecord.model_validate(
        {
            "source": {
                "url": "https://fictional.invalid/program",
                "retrieved_on": "2026-11-02",
                "content_sha256": "a" * 64,
                "format": "html",
                "page_state": "unknown",
            },
            "fields": fields,
            "deadlines_status": "present",
            "deadlines": list(deadlines),
            "conditions": [],
            **changes,
        }
    )


def with_tasks(*deadlines: Deadline) -> RequirementRecord:
    result = record(*deadlines)
    result.fields.recommenders = module_recommenders = result.fields.recommenders.model_validate(
        claim({"count_min": 2, "count_max": 2})
    )
    assert module_recommenders.usable_for_logic
    result.fields.required_documents = result.fields.required_documents.model_validate(
        claim(["Fictional transcript", "Fictional statement"])
    )
    return result


def by_source(result: Checklist, source: str) -> Any:
    return next(item for item in result.items if item.source == source)


def test_policy_defaults_and_provenance() -> None:
    assert (DEFAULT_POLICY.id, DEFAULT_POLICY.version) == ("buffer-default", "1")
    assert DEFAULT_POLICY.submit_buffer_days == 7
    assert DEFAULT_POLICY.recommendation_lead_days == 21
    assert DEFAULT_POLICY.source_note == "project decision, not from any program"
    result = build_checklist(with_tasks(deadline()), NOW)
    assert result.policy == DEFAULT_POLICY
    assert all(
        item.policy_id == "buffer-default" and item.policy_version == "1" for item in result.items
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"submit_buffer_days": -1},
        {"recommendation_lead_days": -1},
        {"submit_buffer_days": True},
        {"recommendation_lead_days": 2.5},
        {"id": ""},
        {"version": ""},
        {"rationale": ""},
        {"source_note": "official program requirement"},
        {"extra": True},
    ],
)
def test_invalid_policy(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BufferPolicy.model_validate({**DEFAULT_POLICY.model_dump(), **changes})


def test_custom_zero_policy_and_frozen_policy() -> None:
    policy = BufferPolicy(
        id="zero",
        version="2",
        rationale="Fictional zero lead",
        submit_buffer_days=0,
        recommendation_lead_days=0,
    )
    result = build_checklist(with_tasks(deadline()), NOW, policy)
    assert {item.due_date for item in result.items} == {date(2026, 11, 30)}
    with pytest.raises(ValidationError):
        policy.submit_buffer_days = 1


def test_known_zone_buffers_and_dependent_dates() -> None:
    result = build_checklist(with_tasks(deadline()), NOW)
    assert by_source(result, "deadlines[0]").due_date == date(2026, 11, 23)
    assert by_source(result, "fields.recommenders").due_date == date(2026, 11, 9)
    assert by_source(result, "fields.required_documents.value[0]").due_date == date(2026, 11, 23)


@pytest.mark.parametrize("day, expected, clamped", [(2, 2, True), (3, 2, True), (9, 2, False)])
def test_boundary_days(day: int, expected: int, clamped: bool) -> None:
    item = build_checklist(record(deadline(date=f"2026-11-{day:02d}")), NOW).items[0]
    assert item.kind == ItemKind.SUBMIT_APPLICATION
    assert item.due_date == date(2026, 11, expected)
    assert (WarningCode.BUFFER_ALREADY_PASSED in item.warnings) == clamped


def test_recommendation_lead_clamped_before_submission_buffer() -> None:
    result = build_checklist(with_tasks(deadline(date="2026-11-10")), NOW)
    assert by_source(result, "fields.recommenders").due_date == NOW.date()
    assert WarningCode.BUFFER_ALREADY_PASSED in by_source(result, "fields.recommenders").warnings
    assert by_source(result, "deadlines[0]").due_date == date(2026, 11, 3)


@pytest.mark.parametrize(
    "time, zone, warnings",
    [
        (None, None, {WarningCode.TIMEZONE_UNKNOWN, WarningCode.TIME_UNKNOWN}),
        ("23:59", "unknown", {WarningCode.TIMEZONE_UNKNOWN}),
    ],
)
def test_unknown_zone_never_buffered(time: str | None, zone: str | None, warnings: set) -> None:
    result = build_checklist(with_tasks(deadline(time=time, timezone=zone)), NOW)
    item = by_source(result, "deadlines[0]")
    assert item.kind == ItemKind.DEADLINE
    assert item.due_date == date(2026, 11, 30) and set(item.warnings) == warnings
    rec = by_source(result, "fields.recommenders")
    assert rec.kind == ItemKind.REQUEST_RECOMMENDATIONS and rec.due_date is None
    assert WarningCode.TIMEZONE_UNKNOWN in rec.warnings
    assert by_source(result, "fields.required_documents.value[0]").due_date == date(2026, 11, 30)
    assert not any(item.kind == ItemKind.SUBMIT_APPLICATION for item in result.items)


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 11, 2, 9, 59, tzinfo=UTC), ItemKind.DEADLINE),
        (datetime(2026, 11, 2, 10, tzinfo=UTC), ItemKind.CHECK_OFFICIAL_PAGE),
        (datetime(2026, 11, 3, 11, 59, tzinfo=UTC), ItemKind.CHECK_OFFICIAL_PAGE),
        (datetime(2026, 11, 3, 12, tzinfo=UTC), ItemKind.CLOSED),
    ],
)
def test_global_window_priority(now: datetime, expected: ItemKind) -> None:
    result = build_checklist(record(deadline(date="2026-11-02", time=None, timezone=None)), now)
    item = result.items[0]
    assert item.kind == expected
    if expected == ItemKind.CHECK_OFFICIAL_PAGE:
        assert item.due_date is None and WarningCode.DATE_ONLY_WINDOW in item.warnings
        assert "date=2026-11-02" in item.title
    if expected == ItemKind.CLOSED:
        assert item.due_date is None and WarningCode.DEADLINE_PASSED in item.warnings


def test_approved_reference_date_exception_for_every_dependent_item() -> None:
    source = with_tasks(deadline(date="2026-11-02"))
    now = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)
    result = build_checklist(source, now, reference_tz=timezone(timedelta(hours=5)))
    assert result.today == date(2026, 11, 3)
    assert compare(source.deadlines[0], now) == "upcoming"
    assert len(result.items) == 4
    for item in result.items:
        assert item.kind == ItemKind.CHECK_OFFICIAL_PAGE and item.due_date is None
        assert WarningCode.REFERENCE_DATE_AFTER_DEADLINE in item.warnings
        assert all(part in item.title for part in ("2026-11-02", "23:59", "timezone=UTC"))
        assert any(quote.quote == "Fictional date evidence" for quote in item.evidence)


def test_mirror_reference_zone_behind_utc_keeps_safe_calendar_date() -> None:
    now = datetime(2026, 11, 3, 0, 30, tzinfo=UTC)
    source = with_tasks(deadline(date="2026-11-02", timezone="UTC-05:00"))
    result = build_checklist(source, now, reference_tz=timezone(timedelta(hours=-5)))
    assert result.today == date(2026, 11, 2)
    assert compare(source.deadlines[0], now) == "upcoming"
    assert all(item.due_date == date(2026, 11, 2) for item in result.items)
    assert all(
        WarningCode.REFERENCE_DATE_AFTER_DEADLINE not in item.warnings for item in result.items
    )


def test_reference_tz_changes_today_not_instant_comparison() -> None:
    source = record(deadline(date="2026-11-03"))
    now = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)
    utc = build_checklist(source, now)
    east = build_checklist(source, now, reference_tz=timezone(timedelta(hours=5)))
    assert utc.today == date(2026, 11, 2) and east.today == date(2026, 11, 3)
    assert utc.items[0].due_date == utc.today and east.items[0].due_date == east.today
    assert utc.now is now and east.now is now
    assert utc.reference_tz is UTC


def test_compare_receives_original_now_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[datetime] = []

    def tracked(deadline: Deadline, supplied: datetime) -> Any:
        calls.append(supplied)
        return compare(deadline, supplied)

    monkeypatch.setattr(module, "compare", tracked)
    now = datetime(2026, 11, 2, 23, 30, tzinfo=timezone(timedelta(hours=-12)))
    build_checklist(with_tasks(deadline()), now, reference_tz=timezone(timedelta(hours=14)))
    assert calls and all(supplied is now for supplied in calls)


def test_duplicate_document_entries_keep_distinct_ids_and_exact_names() -> None:
    source = with_tasks(deadline())
    source.fields.required_documents.value = ["Fictional résumé", "Fictional résumé"]
    result = build_checklist(source, NOW)
    documents = [item for item in result.items if item.kind == ItemKind.PREPARE_DOCUMENT]
    assert len(documents) == 2 and len({item.id for item in documents}) == 2
    assert all("Fictional résumé" in item.title for item in documents)


@pytest.mark.parametrize("zone", [None, "unknown"])
def test_unknown_zone_cross_reference_date_is_never_shown_as_due(zone: str | None) -> None:
    source = with_tasks(
        deadline(date="2026-11-02", time=None if zone is None else "23:59", timezone=zone)
    )
    now = datetime(2026, 11, 3, 1, tzinfo=UTC)
    result = build_checklist(source, now)
    assert compare(source.deadlines[0], now) == "unknown"
    assert all(
        item.kind == ItemKind.CHECK_OFFICIAL_PAGE and item.due_date is None for item in result.items
    )
    assert all(WarningCode.REFERENCE_DATE_AFTER_DEADLINE in item.warnings for item in result.items)


def test_unknown_zone_upcoming_but_reference_date_ahead_is_also_blocked() -> None:
    source = with_tasks(deadline(date="2026-11-02", time=None, timezone=None))
    now = datetime(2026, 11, 2, 9, tzinfo=UTC)
    result = build_checklist(source, now, reference_tz=timezone(timedelta(hours=23)))
    assert compare(source.deadlines[0], now) == "upcoming"
    assert result.today == date(2026, 11, 3)
    assert all(item.due_date is None for item in result.items)
    assert all(WarningCode.REFERENCE_DATE_AFTER_DEADLINE in item.warnings for item in result.items)


def test_two_cycles_and_other_deadline_types() -> None:
    source = with_tasks(
        deadline(date="2025-11-30", cycle_year=2025),
        deadline(),
        deadline(date="2026-12-15", type="recommender"),
    )
    result = build_checklist(source, NOW)
    assert by_source(result, "deadlines[0]").kind == ItemKind.CLOSED
    assert by_source(result, "deadlines[0]").due_date is None
    assert by_source(result, "deadlines[1]").due_date == date(2026, 11, 23)
    assert by_source(result, "deadlines[2]").due_date == date(2026, 12, 8)
    assert by_source(result, "fields.recommenders").due_date == date(2026, 11, 9)


def test_no_submission_anchor_inferred_from_interview() -> None:
    result = build_checklist(with_tasks(deadline(type="interview")), NOW)
    assert by_source(result, "fields.recommenders").due_date is None
    assert by_source(result, "fields.required_documents.value[0]").due_date is None


def test_earliest_unresolved_anchor_not_silently_replaced_by_later_cycle() -> None:
    source = with_tasks(deadline(date="2026-11-02", time=None, timezone=None), deadline())
    result = build_checklist(source, NOW)
    assert by_source(result, "fields.recommenders").kind == ItemKind.CHECK_OFFICIAL_PAGE
    assert by_source(result, "fields.recommenders").due_date is None


def test_verified_rolling_and_no_derived_dates() -> None:
    result = build_checklist(with_tasks(deadline(rolling=True, date=None)), NOW)
    item = by_source(result, "deadlines[0]")
    assert item.kind == ItemKind.APPLY_EARLY and item.due_date is None
    assert item.warnings == (WarningCode.ROLLING,)
    assert all(item.due_date is None for item in result.items)


@pytest.mark.parametrize("verification", ["not_checked", "unverified"])
def test_all_unverified_record_only_checks(verification: str) -> None:
    source = with_tasks(deadline(verification=verification))
    source.fields.recommenders.verification = verification  # type: ignore[assignment]
    source.fields.required_documents.verification = verification  # type: ignore[assignment]
    result = build_checklist(source, NOW)
    assert len(result.items) == 3
    assert all(
        item.kind == ItemKind.CHECK_OFFICIAL_PAGE
        and item.due_date is None
        and WarningCode.UNVERIFIED_SOURCE in item.warnings
        for item in result.items
    )


@pytest.mark.parametrize("status", ["absent", "in_linked_document", "ambiguous"])
def test_deadline_set_status_gates_even_verified_entries(status: str) -> None:
    source = record(deadline(), deadlines_status=status)
    result = build_checklist(source, NOW)
    assert len(result.items) == 1 and result.items[0].kind == ItemKind.CHECK_OFFICIAL_PAGE
    assert result.items[0].due_date is None
    assert result.items[0].evidence[0].quote == source.deadlines[0].evidence[0].quote


def test_ambiguous_deadline_keeps_all_evidence() -> None:
    source = record(
        deadline(
            status="ambiguous",
            date=None,
            verification="verified",
            evidence=[{"quote": "Fictional candidate one"}, {"quote": "Fictional candidate two"}],
        )
    )
    item = build_checklist(source, NOW).items[0]
    assert item.kind == ItemKind.CHECK_OFFICIAL_PAGE
    assert len(item.evidence) == 2 and item.due_date is None


@pytest.mark.parametrize("field", ["recommenders", "required_documents"])
@pytest.mark.parametrize("status", ["ambiguous", "in_linked_document", "absent"])
def test_non_present_fields_never_generate_actions(field: str, status: str) -> None:
    source = with_tasks(deadline())
    data = {
        "status": status,
        "value": None,
        "evidence": [{"quote": "Fictional unclear requirement"}] if status == "ambiguous" else [],
        "linked_url": "https://fictional.invalid/linked"
        if status == "in_linked_document"
        else None,
    }
    old = getattr(source.fields, field)
    setattr(source.fields, field, old.model_validate(data))
    matches = [
        item
        for item in build_checklist(source, NOW).items
        if item.source.startswith(f"fields.{field}")
    ]
    assert (len(matches) == 0) if status == "absent" else (len(matches) == 1)
    assert all(
        item.kind == ItemKind.CHECK_OFFICIAL_PAGE and item.due_date is None for item in matches
    )


def test_explicit_zero_recommenders_and_missing_anchor() -> None:
    source = with_tasks()
    source.fields.recommenders.value.count_max = 0  # type: ignore[union-attr]
    result = build_checklist(source, NOW)
    assert not any(item.source == "fields.recommenders" for item in result.items)
    assert all(item.due_date is None for item in result.items)


def test_order_ids_evidence_copies_and_confidence_independence() -> None:
    source = with_tasks(deadline(), deadline(label="Fictional second"))
    before = deepcopy(source.model_dump())
    first = build_checklist(source, NOW)
    assert first == build_checklist(source, NOW)
    assert source.model_dump() == before
    assert len({item.id for item in first.items}) == len(first.items)
    assert all(
        first.items[i].due_date is not None or first.items[i + 1].due_date is None
        for i in range(len(first.items) - 1)
    )
    dated = [item.due_date for item in first.items if item.due_date is not None]
    assert dated == sorted(dated)
    first.items[0].evidence[0].quote = "Changed output only"
    assert source.model_dump() == before
    baseline = build_checklist(source, NOW)
    source.fields.recommenders.confidence = 0.001
    source.fields.required_documents.confidence = 0.999
    assert build_checklist(source, NOW) == baseline


def test_ties_use_explicit_kind_order_then_id() -> None:
    policy = BufferPolicy(
        id="tie",
        version="1",
        rationale="Fictional tie",
        submit_buffer_days=7,
        recommendation_lead_days=7,
    )
    result = build_checklist(with_tasks(deadline(), deadline(label="Second")), NOW, policy)
    kinds = [item.kind for item in result.items]
    assert kinds == [
        ItemKind.SUBMIT_APPLICATION,
        ItemKind.SUBMIT_APPLICATION,
        ItemKind.REQUEST_RECOMMENDATIONS,
        ItemKind.PREPARE_DOCUMENT,
        ItemKind.PREPARE_DOCUMENT,
    ]
    assert [item.id for item in result.items[:2]] == sorted(item.id for item in result.items[:2])
    assert [item.id for item in result.items[-2:]] == sorted(item.id for item in result.items[-2:])


def test_buffer_calendar_underflow_is_warning_not_invented_date() -> None:
    policy = BufferPolicy(
        id="huge", version="1", rationale="Fictional oversized buffer", submit_buffer_days=10**30
    )
    item = build_checklist(record(deadline()), NOW, policy).items[0]
    assert item.kind == ItemKind.CHECK_OFFICIAL_PAGE and item.due_date is None
    assert WarningCode.BUFFER_OUT_OF_RANGE in item.warnings


@pytest.mark.parametrize(
    "day, time, code",
    [
        ("2027-03-28", "02:30", WarningCode.DST_GAP),
        ("2027-10-31", "02:30", WarningCode.DST_OVERLAP),
    ],
)
def test_resolver_dst_interpretation_warnings_are_visible(
    day: str, time: str, code: WarningCode
) -> None:
    result = build_checklist(
        record(deadline(date=day, time=time, timezone="Europe/Amsterdam")), NOW
    )
    assert code in result.items[0].warnings


def test_naive_now_and_implicit_reference_zone_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_checklist(record(deadline()), datetime(2026, 11, 2))
    with pytest.raises(TypeError, match="reference_tz"):
        build_checklist(record(deadline()), NOW, reference_tz=None)  # type: ignore[arg-type]


def test_no_clock_calls_even_when_clock_methods_explode(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            raise AssertionError("clock called")

        @classmethod
        def today(cls) -> Any:
            raise AssertionError("clock called")

        @classmethod
        def utcnow(cls) -> Any:
            raise AssertionError("clock called")

    supplied = NoClock(2026, 11, 2, 12, tzinfo=UTC)
    monkeypatch.setattr(module, "datetime", NoClock)
    assert build_checklist(record(deadline()), supplied).now is supplied
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "today", "utcnow", "time", "monotonic"}
        for node in ast.walk(tree)
    )


def test_import_boundary_no_profile_extraction_or_llm() -> None:
    root = Path(__file__).resolve().parents[1]
    seen: set[str] = set()

    def inspect(name: str) -> None:
        assert not name.startswith(
            ("scholarscope.profile", "scholarscope.extraction", "scholarscope.llm")
        )
        if name in seen:
            return
        seen.add(name)
        path = root.joinpath(*name.split(".")).with_suffix(".py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imports = (
                [entry.name for entry in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for imported in imports:
                if imported.startswith("scholarscope."):
                    inspect(imported)

    inspect("scholarscope.checklist")
    assert seen == {"scholarscope.checklist", "scholarscope.deadlines", "scholarscope.schema"}


def test_seeded_calendar_safety_across_offsets_cycles_and_reference_zones() -> None:
    rng = random.Random(40)
    for _ in range(600):
        day = date(2026, 11, 2) + timedelta(days=rng.randint(-15, 15))
        zone = rng.choice([None, "unknown", "UTC", "UTC+14:00", "UTC-12:00", "UTC+05:00"])
        source = with_tasks(
            deadline(
                date=day.isoformat(),
                timezone=zone,
                time=None if zone is None else rng.choice(["00:01", "12:00", "23:59"]),
            )
        )
        now = datetime(2026, 11, 2, tzinfo=UTC) + timedelta(
            hours=rng.randint(-360, 360), minutes=30
        )
        reference = rng.choice(
            [
                UTC,
                timezone(timedelta(hours=-12)),
                timezone(timedelta(hours=14)),
                timezone(timedelta(hours=5)),
                ZoneInfo("Europe/Amsterdam"),
            ]
        )
        result = build_checklist(source, now, reference_tz=reference)
        for item in result.items:
            if item.due_date is not None:
                assert item.due_date <= day
                assert compare(source.deadlines[0], now) == "upcoming"
                if WarningCode.BUFFER_ALREADY_PASSED in item.warnings:
                    assert item.due_date == result.today <= day
        assert result == build_checklist(source, now, reference_tz=reference)
