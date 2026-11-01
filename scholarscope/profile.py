"""Private applicant data, never imported by extraction or sent to an LLM.

No I/O, logging, rule verdicts, GPA conversion, clocks or provider dependencies.
Only the explicit JSON dump methods expose values; repr/str and validation
diagnostics are redacted, including nested errors and structured errors().
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from scholarscope.schema import DegreeLevel, NonEmptyString

# Bundled ISO 3166-1 alpha-2 assigned codes (249 entries); no aliases, reserved
# codes, UK, XK or historical codes. Changes require an explicit reviewed update.
# Reference identifier: ISO 3166-1, alpha-2; no runtime lookup/network dependency.
ISO_COUNTRY_CODES = frozenset(
    [
        "AD",
        "AE",
        "AF",
        "AG",
        "AI",
        "AL",
        "AM",
        "AO",
        "AQ",
        "AR",
        "AS",
        "AT",
        "AU",
        "AW",
        "AX",
        "AZ",
        "BA",
        "BB",
        "BD",
        "BE",
        "BF",
        "BG",
        "BH",
        "BI",
        "BJ",
        "BL",
        "BM",
        "BN",
        "BO",
        "BQ",
        "BR",
        "BS",
        "BT",
        "BV",
        "BW",
        "BY",
        "BZ",
        "CA",
        "CC",
        "CD",
        "CF",
        "CG",
        "CH",
        "CI",
        "CK",
        "CL",
        "CM",
        "CN",
        "CO",
        "CR",
        "CU",
        "CV",
        "CW",
        "CX",
        "CY",
        "CZ",
        "DE",
        "DJ",
        "DK",
        "DM",
        "DO",
        "DZ",
        "EC",
        "EE",
        "EG",
        "EH",
        "ER",
        "ES",
        "ET",
        "FI",
        "FJ",
        "FK",
        "FM",
        "FO",
        "FR",
        "GA",
        "GB",
        "GD",
        "GE",
        "GF",
        "GG",
        "GH",
        "GI",
        "GL",
        "GM",
        "GN",
        "GP",
        "GQ",
        "GR",
        "GS",
        "GT",
        "GU",
        "GW",
        "GY",
        "HK",
        "HM",
        "HN",
        "HR",
        "HT",
        "HU",
        "ID",
        "IE",
        "IL",
        "IM",
        "IN",
        "IO",
        "IQ",
        "IR",
        "IS",
        "IT",
        "JE",
        "JM",
        "JO",
        "JP",
        "KE",
        "KG",
        "KH",
        "KI",
        "KM",
        "KN",
        "KP",
        "KR",
        "KW",
        "KY",
        "KZ",
        "LA",
        "LB",
        "LC",
        "LI",
        "LK",
        "LR",
        "LS",
        "LT",
        "LU",
        "LV",
        "LY",
        "MA",
        "MC",
        "MD",
        "ME",
        "MF",
        "MG",
        "MH",
        "MK",
        "ML",
        "MM",
        "MN",
        "MO",
        "MP",
        "MQ",
        "MR",
        "MS",
        "MT",
        "MU",
        "MV",
        "MW",
        "MX",
        "MY",
        "MZ",
        "NA",
        "NC",
        "NE",
        "NF",
        "NG",
        "NI",
        "NL",
        "NO",
        "NP",
        "NR",
        "NU",
        "NZ",
        "OM",
        "PA",
        "PE",
        "PF",
        "PG",
        "PH",
        "PK",
        "PL",
        "PM",
        "PN",
        "PR",
        "PS",
        "PT",
        "PW",
        "PY",
        "QA",
        "RE",
        "RO",
        "RS",
        "RU",
        "RW",
        "SA",
        "SB",
        "SC",
        "SD",
        "SE",
        "SG",
        "SH",
        "SI",
        "SJ",
        "SK",
        "SL",
        "SM",
        "SN",
        "SO",
        "SR",
        "SS",
        "ST",
        "SV",
        "SX",
        "SY",
        "SZ",
        "TC",
        "TD",
        "TF",
        "TG",
        "TH",
        "TJ",
        "TK",
        "TL",
        "TM",
        "TN",
        "TO",
        "TR",
        "TT",
        "TV",
        "TW",
        "TZ",
        "UA",
        "UG",
        "UM",
        "US",
        "UY",
        "UZ",
        "VA",
        "VC",
        "VE",
        "VG",
        "VI",
        "VN",
        "VU",
        "WF",
        "WS",
        "YE",
        "YT",
        "ZA",
        "ZM",
        "ZW",
    ]
)

_SAFE_LOCATIONS = frozenset(
    [
        "id",
        "schema_version",
        "degree_level",
        "field_of_study",
        "gpas",
        "nationalities",
        "language_scores",
        "documents",
        "date_of_birth",
        "years_experience",
        "value",
        "scale",
        "label",
        "test",
        "score",
        "sub_scores",
        "test_date",
        "kind",
        "note",
    ]
)
FiniteNonnegative = Annotated[float, Field(ge=0)]
FinitePositive = Annotated[float, Field(gt=0)]
ShortText = Annotated[str, StringConstraints(max_length=200)]
CountryCode = Annotated[str, Field(json_schema_extra={"enum": sorted(ISO_COUNTRY_CODES)})]


class PrivateModel(BaseModel):
    """Frozen strict data with value-free representations and validation errors.

    Error locations contain only known field names/indices, never arbitrary
    input mapping keys. Explicit model_dump/json serialization is NOT redacted.
    As with all Pydantic models, model_construct/model_copy(update=...) are trusted
    bypass APIs, not validation entry points for untrusted input.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()

    def __repr_args__(self) -> tuple[tuple[None, str], ...]:
        return ((None, "<redacted>"),)

    def __setattr__(self, name: str, value: Any) -> None:
        try:
            super().__setattr__(name, value)
        except ValidationError as exc:
            raise self._redacted_error(exc) from None

    @classmethod
    def _redacted_error(cls, exc: ValidationError) -> ValidationError:
        details: list[InitErrorDetails] = []
        for error in exc.errors(include_url=False):
            location: list[str | int] = []
            for index, part in enumerate(error["loc"]):
                parent = error["loc"][index - 1] if index else None
                if parent == "sub_scores":
                    location.append("entry")  # Even numeric keys can be private data.
                elif isinstance(part, int) and parent in {
                    "gpas",
                    "nationalities",
                    "language_scores",
                    "documents",
                    "entries",
                }:
                    location.append(part)
                else:
                    location.append(part if part in _SAFE_LOCATIONS else "entry")
            # Never retain input, exception contexts, raw messages or mapping keys.
            constraint = error["type"]
            if constraint == "profile_constraint":
                constraint = error.get("ctx", {}).get("constraint", "invalid")
            details.append(
                {
                    "type": PydanticCustomError(
                        "profile_constraint",
                        "constraint failed ({constraint})",
                        {"constraint": constraint},
                    ),
                    "loc": tuple(location),
                    "input": None,
                }
            )
        return ValidationError.from_exception_data(cls.__name__, details, hide_input=True)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> Self:
        # Invalid JSON fails before model validators, so protect that boundary too.
        try:
            return super().model_validate_json(json_data, **kwargs)
        except ValidationError as exc:
            raise cls._redacted_error(exc) from None

    @model_validator(mode="wrap")
    @classmethod
    def redact_errors(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        try:
            return handler(data)
        except ValidationError as exc:
            raise cls._redacted_error(exc) from None


class GPAEntry(PrivateModel):
    value: FiniteNonnegative
    scale: FinitePositive
    label: ShortText | None = None

    @field_validator("scale")
    @classmethod
    def within_scale(cls, scale: float, info: ValidationInfo) -> float:
        # Keep cross-field validation inside PrivateModel's error-redacting
        # wrapper (a subclass's after-model validator would run outside it).
        if "value" in info.data and info.data["value"] > scale:
            raise PydanticCustomError("gpa_value_exceeds_scale", "value must not exceed scale")
        return scale


class LanguageScore(PrivateModel):
    # Exactly LanguageOption.test's non-empty string type: there is no existing
    # enum of IELTS/TOEFL variants. Preserve spelling; do not invent aliases.
    test: NonEmptyString
    score: FiniteNonnegative
    sub_scores: Mapping[NonEmptyString, FiniteNonnegative] | None = None
    test_date: date | None = None

    @field_validator("test_date", mode="before")
    @classmethod
    def json_date(cls, value: Any, info: ValidationInfo) -> Any:
        return _date_from_json(value, info)

    @field_validator("test")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("test_name_blank", "non-blank test name required")
        return value

    @field_validator("sub_scores")
    @classmethod
    def immutable_scores(
        cls,
        value: Mapping[str, float] | None,
    ) -> Mapping[str, float] | None:
        if value is not None:
            if any(not key.strip() for key in value):
                raise PydanticCustomError(
                    "sub_score_name_blank", "non-blank sub-score names required"
                )
            return MappingProxyType(dict(value))
        return None

    @field_serializer("sub_scores")
    def serialize_scores(self, value: Mapping[str, float] | None) -> dict[str, float] | None:
        return None if value is None else dict(value)


class DocumentHeld(PrivateModel):
    # required_documents is list[str], not an enum. Normalize only this local
    # key: strip/collapse whitespace and lowercase; never replace synonyms.
    kind: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def normalized_kind(cls, value: Any) -> Any:
        # Validate the normalized length too: Unicode lowercasing can expand it.
        return " ".join(value.split()).lower() if isinstance(value, str) else value


class Profile(PrivateModel):
    """Only data explicitly supplied by its owner; never an extraction input.

    None is missing, distinct from 0 and empty text/mappings/collections. Empty
    tuples mean no entries supplied, not proof the owner holds none. No defaults
    infer a degree, nationality, GPA scale, score, birth date or experience.
    """

    id: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
    schema_version: Literal["0.1"] = "0.1"
    degree_level: DegreeLevel | None = None
    field_of_study: ShortText | None = None
    gpas: tuple[GPAEntry, ...] = ()
    nationalities: tuple[CountryCode, ...] = ()
    language_scores: tuple[LanguageScore, ...] = ()
    documents: tuple[DocumentHeld, ...] = ()
    date_of_birth: date | None = None
    years_experience: FiniteNonnegative | None = None

    @field_validator("gpas", "nationalities", "language_scores", "documents", mode="before")
    @classmethod
    def json_arrays(cls, value: Any, info: ValidationInfo) -> Any:
        # JSON has arrays, not tuples. The error-redacting wrap validator makes
        # strict tuple/date validation use Python forms in Pydantic 2.12, so
        # decode these two JSON representations explicitly, only in JSON mode.
        return tuple(value) if info.mode == "json" and isinstance(value, list) else value

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def json_date(cls, value: Any, info: ValidationInfo) -> Any:
        return _date_from_json(value, info)

    @field_validator("gpas")
    @classmethod
    def unique_gpas(cls, value: tuple[GPAEntry, ...]) -> tuple[GPAEntry, ...]:
        if len({(entry.value, entry.scale) for entry in value}) != len(value):
            raise PydanticCustomError("duplicate_gpa_pair", "duplicate GPA pair")
        return value

    @field_validator("nationalities")
    @classmethod
    def countries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(code not in ISO_COUNTRY_CODES for code in value):
            raise PydanticCustomError(
                "iso_alpha2_code", "assigned uppercase ISO alpha-2 code required"
            )
        if len(set(value)) != len(value):
            raise PydanticCustomError("duplicate_nationality", "duplicate nationality")
        return value


class GPAScaleMatch(PrivateModel):
    status: Literal["comparable_scale", "no_comparable_scale"]
    entries: tuple[GPAEntry, ...]


def _date_from_json(value: Any, info: ValidationInfo) -> Any:
    if info.mode == "json" and isinstance(value, str):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("ISO calendar date required")
        return parsed
    return value


def gpa_entries_for_scale(profile: Profile, scale: float) -> tuple[GPAEntry, ...]:
    """Exact numeric equality after GPAValue's strict float validation.

    Both Condition GPA and Profile use finite floats: integer 4 becomes 4.0;
    there is no tolerance, rounding, rescaling or proportional conversion.
    Validate only the scale, without including profile values in diagnostics.
    """
    checked = GPAEntry(value=0.0, scale=scale).scale
    return tuple(entry for entry in profile.gpas if entry.scale == checked)


def match_gpa_scale(profile: Profile, scale: float) -> GPAScaleMatch:
    """Report unavailable comparison data, never an eligibility verdict."""
    entries = gpa_entries_for_scale(profile, scale)
    return GPAScaleMatch(
        status="comparable_scale" if entries else "no_comparable_scale", entries=entries
    )


def to_json_schema() -> dict[str, Any]:
    """Same local export mechanism as RequirementRecord; no I/O or values."""
    return Profile.model_json_schema(by_alias=True)
