"""Synthetic private-data contracts; no network, gold labels or snapshots."""

from __future__ import annotations

import ast
import json
import socket
from datetime import date
from pathlib import Path
from typing import Any, get_args

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JSONSchemaError
from pydantic import ValidationError

from scholarscope import profile as module
from scholarscope.profile import (
    ISO_COUNTRY_CODES,
    DocumentHeld,
    GPAEntry,
    LanguageScore,
    Profile,
    gpa_entries_for_scale,
    match_gpa_scale,
    to_json_schema,
)
from scholarscope.schema import DegreeLevel, GPAValue, LanguageOption


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Profile tests must never use a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def full_profile() -> Profile:
    return Profile(
        id="fixture-01",
        degree_level="master",
        field_of_study="Fictional systems",
        gpas=(
            GPAEntry(value=3.5, scale=4, label="undergraduate CGPA"),
            GPAEntry(value=80, scale=100),
        ),
        nationalities=("PK", "JP"),
        language_scores=(
            LanguageScore(
                test="IELTS",
                score=7,
                sub_scores={"reading": 7.5, "writing": 6.5},
                test_date=date(2025, 1, 2),
            ),
        ),
        documents=(DocumentHeld(kind=" Transcript ", note="Fictional copy"),),
        date_of_birth=date(2001, 2, 3),
        years_experience=0,
    )


def test_minimal_profile_has_no_asserted_facts() -> None:
    profile = Profile(id="opaque-01")
    assert profile.schema_version == "0.1"
    assert profile.degree_level is None
    assert profile.date_of_birth is None
    assert profile.years_experience is None
    assert profile.field_of_study is None
    assert (
        profile.gpas == profile.nationalities == profile.language_scores == profile.documents == ()
    )


def test_full_profile_and_json_round_trip() -> None:
    profile = full_profile()
    assert profile.documents[0].kind == "transcript"
    assert profile.gpas[0].value == 3.5
    assert Profile.model_validate_json(profile.model_dump_json()) == profile
    assert Profile.model_validate(profile.model_dump()) == profile
    Draft202012Validator(to_json_schema()).validate(json.loads(profile.model_dump_json()))


@pytest.mark.parametrize(
    "changes",
    [
        {"date_of_birth": "2001-02-30"},
        {"date_of_birth": "20010203"},
        {"date_of_birth": "2001-02-03T00:00:00"},
        {"years_experience": "0"},
        {"gpas": [{"value": "3.5", "scale": 4}]},
        {"gpas": [{"value": True, "scale": 4}]},
        {"language_scores": [{"test": "IELTS", "score": 7, "test_date": "2025-02-30"}]},
        {"language_scores": [{"test": "IELTS", "score": 7, "sub_scores": {"reading": "7"}}]},
    ],
)
def test_json_round_trip_does_not_relax_constraints(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate_json(json.dumps({"id": "fixture", **changes}))


def test_none_zero_and_empty_are_distinct() -> None:
    missing = Profile(id="fixture")
    stated = Profile(
        id="fixture",
        years_experience=0,
        field_of_study="",
        gpas=(GPAEntry(value=0, scale=4, label=""),),
        language_scores=(LanguageScore(test="IELTS", score=0, sub_scores={}),),
    )
    assert missing.years_experience is None and stated.years_experience == 0
    assert missing.field_of_study is None and stated.field_of_study == ""
    assert LanguageScore(test="IELTS", score=0).sub_scores is None
    assert stated.language_scores[0].sub_scores == {}
    assert stated.gpas[0].value == 0 and stated.gpas[0].label == ""
    assert DocumentHeld(kind="transcript").note is None
    assert DocumentHeld(kind="transcript", note="").note == ""


@pytest.mark.parametrize("value", get_args(DegreeLevel))
def test_degree_vocabulary_is_imported(value: Any) -> None:
    assert Profile(id="fixture", degree_level=value).degree_level == value
    assert module.DegreeLevel is DegreeLevel


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"id": "a" * 129},
        {"id": "fictional@example.invalid"},
        {"id": 12},
        {"schema_version": "1"},
        {"degree_level": "MSc"},
        {"field_of_study": "a" * 201},
        {"field_of_study": 5},
        {"years_experience": -1},
        {"years_experience": "2"},
        {"years_experience": True},
        {"years_experience": float("nan")},
        {"years_experience": float("inf")},
        {"years_experience": float("-inf")},
        {"date_of_birth": "2001-02-03"},
        {"nationalities": ["PK"]},
        {"gpas": []},
        {"language_scores": []},
        {"documents": []},
        {"gpas": None},
        {"nationalities": None},
        {"documents": None},
        {"unexpected": "private-sentinel"},
    ],
)
def test_profile_constraint_rejections(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate({"id": "fixture", **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"value": -1},
        {"value": 5},
        {"scale": 0},
        {"scale": -4},
        {"value": "3.5"},
        {"value": True},
        {"scale": "4"},
        {"scale": False},
        {"value": float("nan")},
        {"value": float("inf")},
        {"scale": float("nan")},
        {"scale": float("inf")},
        {"label": "a" * 201},
        {"label": 4},
        {"extra": 1},
    ],
)
def test_gpa_constraints(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GPAEntry.model_validate({"value": 3.5, "scale": 4, **changes})


def test_gpa_no_rounding_conversion_or_normalization() -> None:
    value = 3.500000000000001
    entry = GPAEntry(value=value, scale=4)
    assert entry.value == value and entry.scale == 4.0
    assert isinstance(entry.scale, float)
    profile = Profile(id="fixture", gpas=(entry, GPAEntry(value=80, scale=100)))
    assert gpa_entries_for_scale(profile, 4) == gpa_entries_for_scale(profile, 4.0) == (entry,)
    assert gpa_entries_for_scale(profile, 100) == gpa_entries_for_scale(profile, 100.0)
    assert gpa_entries_for_scale(profile, 4.000000000000001) == ()
    assert GPAValue(value=value, scale=4).scale == entry.scale


def test_different_gpa_scale_is_not_comparable() -> None:
    profile = Profile(id="fixture", gpas=(GPAEntry(value=3.5, scale=4),))
    assert gpa_entries_for_scale(profile, 100) == ()  # 80/100 requirement: no conversion.
    assert match_gpa_scale(profile, 100).status == "no_comparable_scale"
    assert match_gpa_scale(profile, 100).entries == ()
    assert match_gpa_scale(profile, 4).status == "comparable_scale"
    assert match_gpa_scale(Profile(id="fixture"), 4).status == "no_comparable_scale"


@pytest.mark.parametrize("scale", [0, -4, "4", True, float("nan"), float("inf")])
def test_scale_query_is_strict_and_finite(scale: Any) -> None:
    with pytest.raises(ValidationError):
        gpa_entries_for_scale(Profile(id="fixture"), scale)


def test_duplicate_gpa_pairs_ignore_labels_and_numeric_spelling() -> None:
    with pytest.raises(ValidationError):
        Profile(
            id="fixture",
            gpas=(
                GPAEntry(value=3.5, scale=4, label="one"),
                GPAEntry(value=3.5, scale=4.0, label="two"),
            ),
        )
    profile = Profile(id="fixture", gpas=(GPAEntry(value=3, scale=4), GPAEntry(value=3.5, scale=4)))
    assert len(gpa_entries_for_scale(profile, 4)) == 2


@pytest.mark.parametrize(
    "codes", [("pk",), ("UK",), ("XK",), ("ZZ",), ("USA",), (" PK",), ("",), ("US", "US"), ("SU",)]
)
def test_country_rejections(codes: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        Profile(id="fixture", nationalities=codes)


def test_complete_bundled_country_list_and_territories() -> None:
    assert len(ISO_COUNTRY_CODES) == 249
    assert {"GB", "PK", "JP", "US", "AX", "BQ", "SS", "PS", "TW"} <= ISO_COUNTRY_CODES
    for code in sorted(ISO_COUNTRY_CODES):
        assert len(code) == 2 and code.isascii() and code.isalpha() and code.isupper()
        assert Profile(id="fixture", nationalities=(code,)).nationalities == (code,)


@pytest.mark.parametrize(
    "changes",
    [
        {"test": ""},
        {"test": "  "},
        {"test": 1},
        {"score": -1},
        {"score": "7"},
        {"score": True},
        {"score": float("nan")},
        {"score": float("inf")},
        {"sub_scores": {"reading": -1}},
        {"sub_scores": {"reading": "7"}},
        {"sub_scores": {"reading": True}},
        {"sub_scores": {"reading": float("nan")}},
        {"sub_scores": {"reading": float("inf")}},
        {"sub_scores": {"": 7}},
        {"sub_scores": {"  ": 7}},
        {"test_date": "2025-01-02"},
        {"extra": 1},
    ],
)
def test_language_constraints(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LanguageScore.model_validate({"test": "IELTS", "score": 7, **changes})


@pytest.mark.parametrize("test", ["IELTS", "TOEFL iBT", "JLPT", "Fictional Exam"])
def test_language_names_reuse_condition_free_text(test: str) -> None:
    assert LanguageScore(test=test, score=7).test == LanguageOption(test=test, min_overall=7).test
    assert (
        LanguageScore.model_fields["test"].annotation
        == LanguageOption.model_fields["test"].annotation
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": ""},
        {"kind": " \n "},
        {"kind": "a" * 201},
        {"kind": 4},
        {"note": "a" * 1001},
        {"note": 7},
        {"extra": True},
    ],
)
def test_document_constraints(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DocumentHeld.model_validate({"kind": "transcript", **changes})


def test_document_normalization_without_synonyms() -> None:
    assert DocumentHeld(kind="  DEGREE\n Certificate  ").kind == "degree certificate"
    assert DocumentHeld(kind="CV").kind == "cv"
    assert DocumentHeld(kind="Résumé").kind == "résumé"
    assert DocumentHeld(kind="résumé").kind != DocumentHeld(kind="CV").kind


def test_normalized_document_length_is_bounded() -> None:
    with pytest.raises(ValidationError):
        DocumentHeld(kind="İ" * 200)  # Lowercase expands to i + combining dot.
    assert DocumentHeld(kind="  " + "A" * 200 + "  ").kind == "a" * 200


def test_models_and_nested_scores_are_frozen() -> None:
    profile = full_profile()
    with pytest.raises(ValidationError):
        profile.years_experience = 9
    with pytest.raises(ValidationError):
        profile.gpas[0].value = 1
    scores = profile.language_scores[0].sub_scores
    assert scores is not None
    with pytest.raises(TypeError):
        scores["reading"] = 8  # type: ignore[index]
    source = {"reading": 7.0}
    score = LanguageScore(test="IELTS", score=7, sub_scores=source)
    source["reading"] = 8
    assert score.sub_scores == {"reading": 7}


def test_every_representation_is_redacted() -> None:
    profile = full_profile()
    for value in (
        profile,
        profile.gpas[0],
        profile.language_scores[0],
        profile.documents[0],
        match_gpa_scale(profile, 4),
    ):
        assert str(value) == repr(value) == f"{type(value).__name__}(<redacted>)"
        for secret in ("3.5", "PK", "JP", "2001-02-03", "fixture-01", "Fictional copy"):
            assert secret not in repr(value)
    assert "3.5" not in repr([profile])
    assert "3.5" in profile.model_dump_json()  # Explicit serialization is for private use.


@pytest.mark.parametrize(
    "data",
    [
        {"gpas": ({"value": 987654.321, "scale": 4},)},
        {"gpas": ({"value": "private-gpa-sentinel", "scale": 4},)},
        {"nationalities": ("private-country-sentinel",)},
        {
            "language_scores": (
                {"test": "IELTS", "score": 7, "sub_scores": {"private-map-sentinel": -999.123}},
            )
        },
        {"private-key-sentinel": "private-value-sentinel"},
        {987654321: "private-value-sentinel"},
        {"language_scores": ({"test": "IELTS", "score": 7, "sub_scores": {987654321: 7}},)},
        {"degree_level": "private-degree-sentinel"},
        {"date_of_birth": "private-dob-sentinel"},
    ],
)
def test_errors_never_include_values_or_arbitrary_keys(data: dict[Any, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        Profile.model_validate({"id": "fixture-secret-id", **data})
    text = str(caught.value) + repr(caught.value) + str(caught.value.errors()) + caught.value.json()
    for secret in ("987654.321", "987654321", "999.123", "fixture-secret-id", "private-"):
        assert secret not in text
    assert "constraint failed" in text
    assert caught.value.__cause__ is None


def test_frozen_assignment_errors_do_not_retain_values() -> None:
    profile = full_profile()
    with pytest.raises(ValidationError) as caught:
        profile.years_experience = 987654.321
    assert "987654.321" not in str(caught.value) + caught.value.json()


def test_direct_nested_and_json_errors_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    for operation in (
        lambda: GPAEntry(value=987654.321, scale=4),
        lambda: LanguageScore(test="IELTS", score=-999.123),
        lambda: Profile.model_validate_json(
            '{"id":"secret-id","gpas":[{"value":987654.321,"scale":4}]}'
        ),
        lambda: Profile.model_validate_json('{"id":"secret-id", broken'),
    ):
        with pytest.raises(ValidationError) as caught:
            operation()
        diagnostics = str(caught.value) + caught.value.json() + str(caught.value.errors())
        for secret in ("987654.321", "999.123", "secret-id"):
            assert secret not in diagnostics
    assert capsys.readouterr() == ("", "")


def test_gpa_bounds_error_identifies_constraint_without_value() -> None:
    with pytest.raises(ValidationError) as caught:
        Profile(id="fixture", gpas=({"value": 987654.321, "scale": 4},))  # type: ignore[arg-type]
    assert "gpas" in str(caught.value)
    assert "gpa_value_exceeds_scale" in str(caught.value)
    assert "987654.321" not in str(caught.value)


def test_checked_in_json_schema_matches_model() -> None:
    path = Path(__file__).resolve().parents[1] / "eval/schema/profile.schema.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == to_json_schema()
    Draft202012Validator.check_schema(saved)
    with pytest.raises(JSONSchemaError):
        Draft202012Validator(saved).validate({"id": "fixture", "nationalities": ["ZZ"]})


def test_profile_dependencies_cannot_reach_extraction_or_llm() -> None:
    root = Path(__file__).resolve().parents[1]
    seen: set[str] = set()

    def inspect(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        assert not name.startswith(("scholarscope.extraction", "scholarscope.llm"))
        path = root.joinpath(*name.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for imported in imports:
                if imported.startswith("scholarscope."):
                    inspect(imported)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec"}

    inspect("scholarscope.profile")
    assert seen == {"scholarscope.profile", "scholarscope.schema"}


def test_private_storage_patterns_are_git_ignored() -> None:
    root = Path(__file__).resolve().parents[1]
    lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "profiles/" in lines and "*.profile.json" in lines
    assert not hasattr(module, "load_profile") and not hasattr(module, "save_profile")
