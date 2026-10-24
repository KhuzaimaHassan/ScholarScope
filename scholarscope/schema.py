"""Requirement Records compatible with hand labels; no extraction or verification.

Content status and evidence verification answer separate questions. Only issue
#20's deterministic verifier may promote verification from its default. Confidence
is advisory metadata only: nothing may branch on it, including usability for logic.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, timedelta, timezone, tzinfo
from datetime import date as calendar_date
from typing import Annotated, Any, Generic, Literal, Self, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import Field as PydanticField

FieldStatus = Literal["present", "absent", "ambiguous", "in_linked_document"]
Verification = Literal["not_checked", "verified", "unverified"]
DegreeLevel = Literal["bachelor", "master", "phd", "postdoc", "other"]
DeadlineType = Literal[
    "application", "document", "recommender", "scholarship", "interview", "other"
]
OtherConditionKind = Literal[
    "degree_held",
    "nationality_allowed",
    "nationality_excluded",
    "residency",
    "enrollment_status",
    "age_min",
    "age_max",
    "work_experience",
    "field_of_study",
    "other",
]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
ISODate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
T = TypeVar("T")

# Syntax only for IANA names; timezone_info also checks zoneinfo's actual database.
# Numeric UTC offsets must be strictly inside 24 hours (datetime's offset range).
TZ_PATTERN = re.compile(
    r"^(?:unknown|UTC(?:[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?|"
    r"[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)*)$"
)


def timezone_info(name: str) -> tzinfo | None:
    """Validate without normalizing; unknown has no timezone, never an inferred one."""
    if not TZ_PATTERN.fullmatch(name):
        raise ValueError("invalid timezone")
    if name == "unknown":
        return None
    if name == "UTC":
        return UTC
    if name.startswith(("UTC+", "UTC-")):
        hours, minutes = map(int, name[4:].split(":"))
        delta = timedelta(hours=hours, minutes=minutes)
        return timezone(delta if name[3] == "+" else -delta)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("unknown IANA timezone") from exc


class RecordModel(BaseModel):
    """Reject unknown keys, type coercion and non-finite numbers; never repair input."""

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, serialize_by_alias=True
    )


class Evidence(RecordModel):
    quote: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    passage_id: str | None = None
    locator: str | None = None
    # Optional gold-label disambiguation context is preserved, not used as offsets.
    context_before: Annotated[str, StringConstraints(max_length=80)] | None = None
    context_after: Annotated[str, StringConstraints(max_length=80)] | None = None


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple)):
        return bool(value)
    if isinstance(value, BaseModel):
        return bool(value.model_dump(exclude_none=True))
    return True  # Zero and False are values, not missing data.


class Field(RecordModel, Generic[T]):
    """A page claim and independent verification state.

    Confidence is advisory only; nothing may branch on it. `present` never means
    verified. Failed verification retains the value and its failed evidence.
    Setting verified/unverified is reserved for the deterministic verifier (#20),
    not an LLM or the gold converter; this model validates states, not provenance.
    """

    status: FieldStatus
    value: T | None
    evidence: list[Evidence]
    verification: Verification = "not_checked"
    linked_url: NonEmptyString | None = None
    notes: str | None = None
    confidence: float | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.status == "present" and not _has_value(self.value):
            raise ValueError("present requires a non-empty value")
        if self.status in {"present", "ambiguous"} and not self.evidence:
            raise ValueError(f"{self.status} requires at least one evidence quote")
        if self.status != "present" and self.value is not None:
            raise ValueError(f"{self.status} requires value None")
        if self.status in {"absent", "in_linked_document"}:
            if self.evidence:
                raise ValueError(f"{self.status} requires no evidence")
            if self.verification != "not_checked":
                raise ValueError(f"{self.status} requires verification not_checked")
        if self.status == "in_linked_document" and not (
            self.linked_url and self.linked_url.strip()
        ):
            raise ValueError("in_linked_document requires linked_url")
        if self.verification != "not_checked" and not self.evidence:
            raise ValueError("verified or unverified requires at least one evidence quote")
        return self

    @property
    def usable_for_logic(self) -> bool:
        """Encode ADR 008: only present claims with verified evidence are usable."""
        return self.status == "present" and self.verification == "verified"


class FundingCoverage(RecordModel):
    item: Literal["tuition", "stipend", "travel", "insurance", "housing", "visa", "other"]
    amount: float | None = None
    amount_max: float | None = None
    currency: str | None = None
    period: Literal["one_time", "month", "year", "programme"] | None = None
    note: str | None = None


class Recommenders(RecordModel):
    count_min: Annotated[int, PydanticField(ge=0)] | None = None
    count_max: Annotated[int, PydanticField(ge=0)] | None = None
    type: str | None = None


class RequirementFields(RecordModel):
    program_name: Field[str]
    institution: Field[str]
    degree_levels: Field[list[DegreeLevel]]
    funding_coverage: Field[list[FundingCoverage]]
    required_documents: Field[list[str]]
    recommenders: Field[Recommenders]
    application_link: Field[str]


class GPAValue(RecordModel):
    value: float
    scale: float


class LanguageOption(RecordModel):
    test: NonEmptyString
    min_overall: float
    min_subscore: float | None = None


class LanguageValue(RecordModel):
    logic: Literal["any", "all"]
    options: Annotated[list[LanguageOption], PydanticField(min_length=1)]


class ConditionBase(RecordModel):
    """An evidence-bearing claim; verifier state never establishes value support."""

    required: bool
    applies_to: str | None
    evidence: Annotated[list[Evidence], PydanticField(min_length=1)]
    notes: str | None = None
    verification: Verification = "not_checked"

    @property
    def usable_for_logic(self) -> bool:
        """Conditions are claims (no absent status); only checked presence is usable."""
        return self.verification == "verified"


class GPACondition(ConditionBase):
    kind: Literal["min_gpa"]
    value: GPAValue


class LanguageCondition(ConditionBase):
    kind: Literal["language"]
    value: LanguageValue


class OtherCondition(ConditionBase):
    kind: OtherConditionKind
    value: JsonValue


Condition = Annotated[
    GPACondition | LanguageCondition | OtherCondition, PydanticField(discriminator="kind")
]


class Deadline(RecordModel):
    """Gold-compatible deadline plus verifier-owned state; resolution is separate."""

    label: NonEmptyString
    type: DeadlineType
    cycle_year: int | None
    date: ISODate | None
    time: Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")] | None
    timezone: str | None
    rolling: bool
    status: Literal["present", "ambiguous"]
    evidence: list[Evidence]
    notes: str | None = None
    verification: Verification = "not_checked"

    @field_validator("date")
    @classmethod
    def valid_calendar_date(cls, value: str | None) -> str | None:
        if value is not None:
            calendar_date.fromisoformat(value)
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            timezone_info(value)
        return value

    @model_validator(mode="after")
    def validate_deadline(self) -> Self:
        if not self.evidence:
            raise ValueError(f"status '{self.status}' needs at least one evidence quote")
        if self.rolling and self.date is not None:
            raise ValueError("rolling deadline must have date null")
        if self.status == "present" and not self.rolling and self.date is None:
            raise ValueError("present, non-rolling deadline needs a date")
        if self.status == "ambiguous" and self.date is not None:
            raise ValueError("ambiguous deadline must have date null")
        if self.time is not None and self.timezone is None:
            raise ValueError("time given, so timezone must be set (use 'unknown' if not stated)")
        if self.time is None and self.timezone is not None:
            raise ValueError("timezone set without a time; use null")
        return self

    @property
    def usable_for_logic(self) -> bool:
        """ADR 008/010: neutral resolution cannot make unchecked evidence usable."""
        return self.status == "present" and self.verification == "verified"


class Source(RecordModel):
    url: NonEmptyString
    retrieved_on: ISODate
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    format: Literal["html", "pdf"]
    page_state: Literal["open", "closed", "upcoming", "unknown"]
    language: Annotated[str, StringConstraints(min_length=2)] | None = None
    cycle_label: str | None = None
    is_mirror: bool | None = None
    owner_org: str | None = None

    @field_validator("retrieved_on")
    @classmethod
    def valid_retrieval_date(cls, value: str) -> str:
        calendar_date.fromisoformat(value)
        return value


class Slot(RecordModel):
    family: NonEmptyString
    number: Annotated[int, PydanticField(ge=1, le=4)]


class Labeler(RecordModel):
    id: NonEmptyString
    pass_: Annotated[int, PydanticField(alias="pass", ge=1)]
    labeled_on: ISODate
    minutes_spent: Annotated[float, PydanticField(ge=0)]

    @field_validator("labeled_on")
    @classmethod
    def valid_label_date(cls, value: str) -> str:
        calendar_date.fromisoformat(value)
        return value


class RequirementRecord(RecordModel):
    schema_version: Literal["0.1"] = "0.1"
    source: Source
    fields: RequirementFields
    deadlines_status: FieldStatus
    deadlines: list[Deadline]
    conditions: list[Condition]
    prompt_version: str | None = None
    model: str | None = None
    # Label-only metadata is optional for extraction, preserved for comparison.
    program_slug: str | None = None
    slot: Slot | None = None
    labeler: Labeler | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def no_duplicate_deadlines(self) -> Self:
        seen: set[tuple[str, int | None, str | None, str | None, str | None, str]] = set()
        for deadline in self.deadlines:
            key = (
                deadline.type,
                deadline.cycle_year,
                deadline.date,
                deadline.time,
                deadline.timezone,
                deadline.label,
            )
            if key in seen:
                raise ValueError(
                    "exact duplicate deadline (type, cycle_year, date, time, timezone, label)"
                )
            seen.add(key)
        return self


def to_json_schema() -> dict[str, Any]:
    """Export a local JSON Schema; no network, extraction, or verifier calls."""
    return RequirementRecord.model_json_schema(by_alias=True)


def from_gold_label(label: dict[str, Any]) -> RequirementRecord:
    """Copy gold claims without treating a human label as verifier output.

    This is a structural converter, not the hand-label validator. It does not
    establish quote presence/support or turn unfinished skeletons into gold truth.
    No label or snapshot files are read or written here.
    """
    data = deepcopy(label)
    for field in data["fields"].values():
        field["verification"] = "not_checked"
    for deadline in data["deadlines"]:
        deadline["verification"] = "not_checked"
    for condition in data["conditions"]:
        condition["verification"] = "not_checked"
    return RequirementRecord.model_validate(data)
