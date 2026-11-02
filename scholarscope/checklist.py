"""Pure, evidence-gated calendar planning; no clocks, I/O, profiles or providers.

Source claims remain untrusted text. Verification establishes quote presence,
not support or truth. Confidence is never consulted. All deadline comparisons
delegate to deadlines.compare with the caller's original aware instant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from scholarscope.deadlines import compare, resolve
from scholarscope.schema import Deadline, Evidence, RequirementRecord

NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class BufferPolicy(BaseModel):
    """Project planning defaults, never a requirement inferred from a source."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    id: NonEmpty
    version: NonEmpty
    submit_buffer_days: Annotated[int, Field(ge=0)] = 7
    recommendation_lead_days: Annotated[int, Field(ge=0)] = 21
    rationale: NonEmpty
    source_note: Literal["project decision, not from any program"] = (
        "project decision, not from any program"
    )


DEFAULT_POLICY = BufferPolicy(
    id="buffer-default",
    version="1",
    rationale="Plan submission seven calendar days early and request recommendations "
    "twenty-one calendar days before the stated deadline. These are configurable "
    "project working defaults, not measured guarantees or program requirements.",
)


class ItemKind(StrEnum):
    SUBMIT_APPLICATION = "submit_application"
    REQUEST_RECOMMENDATIONS = "request_recommendations"
    PREPARE_DOCUMENT = "prepare_document"
    CHECK_OFFICIAL_PAGE = "check_official_page"
    CLOSED = "closed"
    APPLY_EARLY = "apply_early"
    DEADLINE = "deadline"


class WarningCode(StrEnum):
    TIMEZONE_UNKNOWN = "TIMEZONE_UNKNOWN"
    TIME_UNKNOWN = "TIME_UNKNOWN"
    DATE_ONLY_WINDOW = "DATE_ONLY_WINDOW"
    DEADLINE_PASSED = "DEADLINE_PASSED"
    UNVERIFIED_SOURCE = "UNVERIFIED_SOURCE"
    ROLLING = "ROLLING"
    BUFFER_ALREADY_PASSED = "BUFFER_ALREADY_PASSED"
    REFERENCE_DATE_AFTER_DEADLINE = "REFERENCE_DATE_AFTER_DEADLINE"
    DEADLINE_UNAVAILABLE = "DEADLINE_UNAVAILABLE"
    BUFFER_OUT_OF_RANGE = "BUFFER_OUT_OF_RANGE"
    DST_GAP = "DST_GAP"
    DST_OVERLAP = "DST_OVERLAP"


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    kind: ItemKind
    title: str
    due_date: date | None
    warnings: tuple[WarningCode, ...]
    source: str
    evidence: tuple[Evidence, ...]
    policy_id: str
    policy_version: str


@dataclass(frozen=True)
class Checklist:
    items: tuple[ChecklistItem, ...]
    now: datetime
    reference_tz: tzinfo
    today: date
    policy: BufferPolicy


# Explicit display order, independent of lexical enum values or dict ordering.
_KIND_ORDER = (
    ItemKind.SUBMIT_APPLICATION,
    ItemKind.REQUEST_RECOMMENDATIONS,
    ItemKind.PREPARE_DOCUMENT,
    ItemKind.DEADLINE,
    ItemKind.CHECK_OFFICIAL_PAGE,
    ItemKind.CLOSED,
    ItemKind.APPLY_EARLY,
)


def _stated(deadline: Deadline) -> str:
    """Show raw date/time/zone; None remains explicitly unstated, not inferred."""
    return (
        f"{deadline.label} (type={deadline.type}, cycle={deadline.cycle_year}, "
        f"date={deadline.date}, time={deadline.time}, timezone={deadline.timezone})"
    )


def _warnings(deadline: Deadline) -> tuple[WarningCode, ...]:
    codes: list[WarningCode] = []
    if deadline.timezone in {None, "unknown"}:
        codes.append(WarningCode.TIMEZONE_UNKNOWN)
    if deadline.time is None:
        codes.append(WarningCode.TIME_UNKNOWN)
    reason = resolve(deadline).reason
    if reason.startswith("nonexistent local time"):
        codes.append(WarningCode.DST_GAP)
    elif reason.startswith("ambiguous local time"):
        codes.append(WarningCode.DST_OVERLAP)
    return tuple(codes)


def build_checklist(
    record: RequirementRecord,
    now: datetime,
    policy: BufferPolicy = DEFAULT_POLICY,
    *,
    reference_tz: tzinfo = UTC,
) -> Checklist:
    """Plan from verified claims, without changing input or reading a clock.

    today is now.astimezone(reference_tz).date(), not the machine's calendar.
    Recommendation leads use the raw application/scholarship deadline, not the
    already buffered submission date. Documents inherit that anchor's planned
    submission date (or its explicitly unbuffered date), never a separate buffer.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(reference_tz, tzinfo):
        raise TypeError("reference_tz must be an explicit tzinfo")
    today = now.astimezone(reference_tz).date()
    items: list[ChecklistItem] = []

    def emit(
        kind: ItemKind,
        title: str,
        source: str,
        evidence: list[Evidence],
        due: date | None = None,
        warnings: tuple[WarningCode, ...] = (),
        anchor: Deadline | None = None,
    ) -> ChecklistItem:
        identity = {
            "url": record.source.url,
            "source": source,
            "kind": kind.value,
            "policy": policy.model_dump(),
            "anchor": None
            if anchor is None
            else [
                anchor.type,
                anchor.cycle_year,
                anchor.label,
                anchor.date,
                anchor.time,
                anchor.timezone,
                anchor.rolling,
            ],
        }
        key = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        item = ChecklistItem(
            id="c-" + hashlib.sha256(key.encode("utf-8")).hexdigest(),
            kind=kind,
            title=title,
            due_date=due,
            warnings=tuple(sorted(set(warnings))),
            source=source,
            evidence=tuple(quote.model_copy(deep=True) for quote in evidence),
            policy_id=policy.id,
            policy_version=policy.version,
        )
        items.append(item)
        return item

    def planned(
        deadline: Deadline,
        kind: ItemKind,
        title: str,
        source: str,
        evidence: list[Evidence],
        days: int,
    ) -> ChecklistItem:
        warnings = _warnings(deadline)
        text = f"{title}: {_stated(deadline)}"
        state = compare(deadline, now)  # Original aware instant, unchanged.
        if state == "past":
            return emit(
                ItemKind.CLOSED,
                text,
                source,
                evidence,
                warnings=warnings + (WarningCode.DEADLINE_PASSED,),
                anchor=deadline,
            )
        stated_date = date.fromisoformat(deadline.date) if deadline.date else None
        if stated_date is not None and today > stated_date:
            # Applies to upcoming AND unknown, including all dependent tasks.
            return emit(
                ItemKind.CHECK_OFFICIAL_PAGE,
                text,
                source,
                evidence,
                warnings=warnings
                + (WarningCode.REFERENCE_DATE_AFTER_DEADLINE,)
                + ((WarningCode.DATE_ONLY_WINDOW,) if state == "unknown" else ()),
                anchor=deadline,
            )
        if state == "unknown":
            return emit(
                ItemKind.CHECK_OFFICIAL_PAGE,
                text,
                source,
                evidence,
                warnings=warnings + (WarningCode.DATE_ONLY_WINDOW,),
                anchor=deadline,
            )
        if deadline.timezone in {None, "unknown"}:
            if kind == ItemKind.SUBMIT_APPLICATION:
                kind = ItemKind.DEADLINE
            return emit(
                kind,
                text,
                source,
                evidence,
                due=None if kind == ItemKind.REQUEST_RECOMMENDATIONS else stated_date,
                warnings=warnings,
                anchor=deadline,
            )
        if stated_date is None:
            return emit(
                ItemKind.CHECK_OFFICIAL_PAGE,
                text,
                source,
                evidence,
                warnings=warnings + (WarningCode.DEADLINE_UNAVAILABLE,),
                anchor=deadline,
            )
        try:
            due = stated_date - timedelta(days=days)
        except OverflowError:
            return emit(
                ItemKind.CHECK_OFFICIAL_PAGE,
                text,
                source,
                evidence,
                warnings=warnings + (WarningCode.BUFFER_OUT_OF_RANGE,),
                anchor=deadline,
            )
        if due < today:
            due = today
            warnings += (WarningCode.BUFFER_ALREADY_PASSED,)
        return emit(kind, text, source, evidence, due, warnings, deadline)

    # Candidate anchors exclude closed cycles and rolling/non-date entries.
    # Unknown/cross-calendar anchors are retained so dependent tasks warn instead
    # of silently skipping an earlier unresolved deadline in favor of a later one.
    anchors: list[tuple[date, int, Deadline]] = []
    if record.deadlines_status in {"absent", "in_linked_document"} or not record.deadlines:
        emit(
            ItemKind.CHECK_OFFICIAL_PAGE,
            "Check official deadline information",
            "deadlines_status",
            [quote for deadline in record.deadlines for quote in deadline.evidence],
            warnings=(WarningCode.UNVERIFIED_SOURCE,),
        )
    else:
        for index, deadline in enumerate(record.deadlines):
            source = f"deadlines[{index}]"
            if record.deadlines_status != "present" or not deadline.usable_for_logic:
                emit(
                    ItemKind.CHECK_OFFICIAL_PAGE,
                    f"Check official page: {_stated(deadline)}",
                    source,
                    deadline.evidence,
                    warnings=(WarningCode.UNVERIFIED_SOURCE,),
                    anchor=deadline,
                )
            elif deadline.rolling:
                emit(
                    ItemKind.APPLY_EARLY,
                    f"Apply early: {_stated(deadline)}",
                    source,
                    deadline.evidence,
                    warnings=(WarningCode.ROLLING,),
                    anchor=deadline,
                )
            else:
                planned(
                    deadline,
                    ItemKind.SUBMIT_APPLICATION,
                    "Complete deadline step",
                    source,
                    deadline.evidence,
                    policy.submit_buffer_days,
                )
                if (
                    deadline.type in {"application", "scholarship"}
                    and deadline.date is not None
                    and compare(deadline, now) != "past"
                ):
                    anchors.append((date.fromisoformat(deadline.date), index, deadline))
    earliest = min(anchors, key=lambda entry: (entry[0], entry[1]))[2] if anchors else None

    recommenders = record.fields.recommenders
    if recommenders.status != "absent":
        source = "fields.recommenders"
        if not recommenders.usable_for_logic:
            emit(
                ItemKind.CHECK_OFFICIAL_PAGE,
                "Check official recommendation requirements",
                source,
                recommenders.evidence,
                warnings=(WarningCode.UNVERIFIED_SOURCE,),
            )
        elif recommenders.value is not None and recommenders.value.count_max == 0:
            pass  # An explicit zero maximum does not create a request for letters.
        elif earliest is None:
            emit(
                ItemKind.REQUEST_RECOMMENDATIONS,
                "Request recommendations; no usable fixed deadline",
                source,
                recommenders.evidence,
                warnings=(WarningCode.DEADLINE_UNAVAILABLE,),
            )
        else:
            planned(
                earliest,
                ItemKind.REQUEST_RECOMMENDATIONS,
                "Request recommendations",
                source,
                recommenders.evidence + earliest.evidence,
                policy.recommendation_lead_days,
            )

    documents = record.fields.required_documents
    if documents.status != "absent":
        if not documents.usable_for_logic:
            emit(
                ItemKind.CHECK_OFFICIAL_PAGE,
                "Check official document requirements",
                "fields.required_documents",
                documents.evidence,
                warnings=(WarningCode.UNVERIFIED_SOURCE,),
            )
        elif documents.value is not None:
            for index, document in enumerate(documents.value):
                source = f"fields.required_documents.value[{index}]"
                if earliest is None:
                    emit(
                        ItemKind.PREPARE_DOCUMENT,
                        f"Prepare document: {document}",
                        source,
                        documents.evidence,
                        warnings=(WarningCode.DEADLINE_UNAVAILABLE,),
                    )
                else:
                    planned(
                        earliest,
                        ItemKind.PREPARE_DOCUMENT,
                        f"Prepare document: {document}",
                        source,
                        documents.evidence + earliest.evidence,
                        policy.submit_buffer_days,
                    )

    return Checklist(
        items=tuple(
            sorted(
                items,
                key=lambda item: (
                    item.due_date is None,
                    item.due_date or date.max,
                    _KIND_ORDER.index(item.kind),
                    item.id,
                ),
            )
        ),
        now=now,
        reference_tz=reference_tz,
        today=today,
        policy=policy.model_copy(deep=True),
    )
