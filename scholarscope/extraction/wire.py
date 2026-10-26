"""Small provider schemas, NOT domain contracts or evidence verification.

All properties are required (nullable where appropriate), with no constrained
strings, defaults, consts or discriminators. Domain validation happens locally.
Unrequested properties, including model-claimed verification, are ignored.
"""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, JsonValue

from scholarscope.schema import DeadlineType, DegreeLevel, FieldStatus, OtherConditionKind

T = TypeVar("T")


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)


class WireEvidence(WireModel):
    quote: str
    passage_id: str | None


class WireField(WireModel, Generic[T]):
    status: FieldStatus
    value: T | None
    evidence: list[WireEvidence]
    linked_url: str | None
    notes: str | None


class WireFunding(WireModel):
    item: Literal["tuition", "stipend", "travel", "insurance", "housing", "visa", "other"]
    amount: float | None
    amount_max: float | None
    currency: str | None
    period: Literal["one_time", "month", "year", "programme"] | None
    note: str | None


class WireRecommenders(WireModel):
    count_min: int | None
    count_max: int | None
    type: str | None


class IdentityGroup(WireModel):
    program_name: WireField[str]
    institution: WireField[str]
    application_link: WireField[str]
    degree_levels: WireField[list[DegreeLevel]]


class FundingGroup(WireModel):
    funding_coverage: WireField[list[WireFunding]]


class DocumentsGroup(WireModel):
    required_documents: WireField[list[str]]
    recommenders: WireField[WireRecommenders]


class WireDeadline(WireModel):
    label: str
    type: DeadlineType
    cycle_year: int | None
    date: str | None
    time: str | None
    timezone: str | None
    rolling: bool
    status: Literal["present", "ambiguous"]
    evidence: list[WireEvidence]
    notes: str | None


class DeadlinesGroup(WireModel):
    deadlines_status: FieldStatus
    deadlines: list[WireDeadline]
    linked_url: str | None
    notes: str | None


class WireGPA(WireModel):
    value: float
    scale: float


class WireLanguageOption(WireModel):
    test: str
    min_overall: float
    min_subscore: float | None


class WireLanguage(WireModel):
    logic: Literal["any", "all"]
    options: list[WireLanguageOption]


class WireCondition(WireModel):
    # Multiple enum values avoid const; no tagged/discriminated provider union.
    kind: Literal["min_gpa", "language"] | OtherConditionKind
    value: WireGPA | WireLanguage | JsonValue
    required: bool
    applies_to: str | None
    evidence: list[WireEvidence]
    notes: str | None


class ConditionsGroup(WireModel):
    conditions: list[WireCondition]


GROUP_MODELS: dict[str, type[WireModel]] = {
    "identity": IdentityGroup,
    "funding": FundingGroup,
    "documents": DocumentsGroup,
    "deadlines": DeadlinesGroup,
    "conditions": ConditionsGroup,
}
