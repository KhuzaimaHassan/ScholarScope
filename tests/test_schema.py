"""Fictional inputs only; no real labels, page snapshots, or external services."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from scholarscope.schema import (
    Condition,
    Deadline,
    Evidence,
    Field,
    FundingCoverage,
    GPAValue,
    LanguageValue,
    Recommenders,
    RequirementFields,
    RequirementRecord,
    Source,
    from_gold_label,
    to_json_schema,
)

ROOT = Path(__file__).resolve().parent.parent


def example() -> dict[str, Any]:
    return json.loads((ROOT / "eval/gold/_example-fictional.json").read_text(encoding="utf-8"))


def field_data(**overrides: Any) -> dict[str, Any]:
    return {
        "status": "present",
        "value": "Fictional claim",
        "evidence": [{"quote": "Fictional supporting text"}],
        **overrides,
    }


@pytest.mark.parametrize("length", [1, 400])
def test_evidence_quote_boundaries(length: int) -> None:
    evidence = Evidence(quote="x" * length)
    assert len(evidence.quote) == length
    assert evidence.passage_id is None and evidence.locator is None


@pytest.mark.parametrize("quote", ["", "x" * 401, 12])
def test_invalid_evidence_quotes(quote: Any) -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate({"quote": quote})


def test_evidence_preserves_context_and_has_no_offsets() -> None:
    evidence = Evidence(quote="Repeated text", context_before="Before", locator="p.3")
    assert evidence.context_before == "Before"
    with pytest.raises(ValidationError):
        Evidence.model_validate({"quote": "Text", "start": 0, "end": 4})


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"verification": "verified"},
        {"verification": "unverified"},
        {"status": "ambiguous", "value": None},
        {"status": "ambiguous", "value": None, "verification": "verified"},
        {"status": "ambiguous", "value": None, "verification": "unverified"},
        {"status": "absent", "value": None, "evidence": []},
        {
            "status": "in_linked_document",
            "value": None,
            "evidence": [],
            "linked_url": "https://example.org/checklist",
        },
    ],
)
def test_valid_field_states(overrides: dict[str, Any]) -> None:
    data = field_data(**overrides)
    field = Field[str].model_validate(data)
    assert field.status == data["status"]
    assert field.value == data["value"]
    assert field.verification == data.get("verification", "not_checked")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"value": None}, "non-empty value"),
        ({"value": ""}, "non-empty value"),
        ({"value": " \t"}, "non-empty value"),
        ({"evidence": []}, "at least one evidence quote"),
        ({"status": "ambiguous", "value": None, "evidence": []}, "evidence quote"),
        ({"status": "ambiguous"}, "value None"),
        ({"status": "absent", "evidence": []}, "value None"),
        ({"status": "absent", "value": None}, "no evidence"),
        ({"status": "in_linked_document", "value": None, "evidence": []}, "linked_url"),
        (
            {"status": "in_linked_document", "value": None, "evidence": [], "linked_url": "   "},
            "linked_url",
        ),
        ({"status": "in_linked_document", "linked_url": "https://example.org"}, "value None"),
        (
            {"status": "in_linked_document", "value": None, "linked_url": "https://example.org"},
            "no evidence",
        ),
        ({"verification": "verified", "evidence": []}, "evidence quote"),
        ({"verification": "unverified", "evidence": []}, "evidence quote"),
        ({"status": "verified"}, "literal"),
        ({"status": "unverified"}, "literal"),
        ({"verification": "present"}, "literal"),
    ],
)
def test_invalid_field_states(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Field[str].model_validate(field_data(**overrides))


@pytest.mark.parametrize("status", ["absent", "in_linked_document"])
@pytest.mark.parametrize("verification", ["verified", "unverified"])
def test_non_claims_cannot_be_verified(status: str, verification: str) -> None:
    with pytest.raises(ValidationError, match="verification not_checked"):
        Field[str].model_validate(
            field_data(
                status=status,
                verification=verification,
                value=None,
                evidence=[],
                linked_url="https://example.org/checklist",
            )
        )


@pytest.mark.parametrize("verification", ["not_checked", "verified", "unverified"])
@pytest.mark.parametrize("confidence", [None, 0.0, 1.0, 99.0])
def test_usability_never_depends_on_confidence(verification: str, confidence: float | None) -> None:
    data = field_data(verification=verification, confidence=confidence)
    field = Field[str].model_validate(data)
    assert field.usable_for_logic == (verification == "verified")
    assert field.value == data["value"]
    assert field.evidence[0].quote == data["evidence"][0]["quote"]
    assert "usable_for_logic" not in field.model_dump()


@pytest.mark.parametrize("verification", ["not_checked", "verified", "unverified"])
def test_ambiguous_is_never_usable(verification: str) -> None:
    field = Field[str].model_validate(
        field_data(
            status="ambiguous",
            value=None,
            verification=verification,
        )
    )
    assert not field.usable_for_logic


@pytest.mark.parametrize("status", ["absent", "in_linked_document"])
def test_non_present_is_not_usable(status: str) -> None:
    field = Field[str].model_validate(
        field_data(
            status=status,
            value=None,
            evidence=[],
            linked_url="https://example.org/checklist",
        )
    )
    assert not field.usable_for_logic


def test_empty_collection_and_empty_model_are_not_present_values() -> None:
    with pytest.raises(ValidationError, match="non-empty value"):
        Field[list[str]].model_validate(field_data(value=[]))
    with pytest.raises(ValidationError, match="non-empty value"):
        Field[Recommenders].model_validate(field_data(value={}))
    assert Field[int].model_validate(field_data(value=0)).value == 0
    assert Field[bool].model_validate(field_data(value=False)).value is False


def test_failed_verification_retains_value_and_quote_through_json() -> None:
    original = Field[str].model_validate(field_data(verification="unverified"))
    restored = Field[str].model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.value == "Fictional claim"
    assert restored.evidence[0].quote == "Fictional supporting text"
    assert not restored.usable_for_logic


@pytest.mark.parametrize("confidence", ["0.5", float("nan"), float("inf")])
def test_invalid_confidence_is_not_coerced(confidence: Any) -> None:
    with pytest.raises(ValidationError):
        Field[str].model_validate(field_data(confidence=confidence))


def test_gold_converter_and_json_round_trip() -> None:
    gold = example()
    before = deepcopy(gold)
    record = from_gold_label(gold)
    assert gold == before
    assert record.schema_version == "0.1"
    assert record.source.model_dump(exclude_none=True) == gold["source"]
    assert record.program_slug == gold["program_slug"]
    assert record.labeler is not None
    assert record.labeler.model_dump() == gold["labeler"]
    for name, label_field in gold["fields"].items():
        field = getattr(record.fields, name)
        assert field.verification == "not_checked"
        assert not field.usable_for_logic
        for key in ("status", "value", "evidence"):
            value = field.model_dump(exclude_none=True)[key] if key != "value" else field.value
            if key == "evidence":
                value = [e.model_dump(exclude_none=True) for e in field.evidence]
            elif key == "value" and hasattr(value, "model_dump"):
                value = value.model_dump(exclude_none=True)
            elif key == "value" and isinstance(value, list):
                value = [
                    v.model_dump(exclude_none=True) if hasattr(v, "model_dump") else v
                    for v in value
                ]
            assert value == label_field[key]
    assert record.conditions[0].value == GPAValue(value=3.5, scale=4.0)
    assert RequirementRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("verification", ["verified", "unverified"])
def test_converter_cannot_mark_gold_as_verified(verification: str) -> None:
    gold = example()
    for data in gold["fields"].values():
        data["verification"] = verification
    record = from_gold_label(gold)
    assert all(
        getattr(record.fields, n).verification == "not_checked"
        for n in RequirementFields.model_fields
    )


def property_names(node: Any) -> set[str]:
    if isinstance(node, dict):
        own = set(node.get("properties", {}))
        return own.union(*(property_names(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(property_names(v) for v in node))
    return set()


def test_schema_export_and_gold_field_name_drift_guard() -> None:
    gold = json.loads((ROOT / "eval/schema/gold-label.schema.json").read_text(encoding="utf-8"))
    exported = to_json_schema()
    Draft202012Validator.check_schema(exported)
    assert property_names(gold) <= property_names(exported)
    assert set(gold["properties"]["fields"]["properties"]) == set(RequirementFields.model_fields)
    assert set(gold["properties"]["source"]["properties"]) == set(Source.model_fields)
    Draft202012Validator(exported).validate(
        json.loads(from_gold_label(example()).model_dump_json())
    )


@pytest.mark.parametrize(
    "name, value",
    [
        ("degree_levels", ["graduate"]),
        ("funding_coverage", [{"item": "books"}]),
        ("required_documents", [12]),
        ("recommenders", {"count_min": -1}),
        ("program_name", 12),
        ("application_link", 12),
    ],
)
def test_typed_requirement_values(name: str, value: Any) -> None:
    gold = example()
    gold["fields"][name] = field_data(value=value)
    with pytest.raises(ValidationError):
        from_gold_label(gold)


@pytest.mark.parametrize(
    "key, value",
    [
        ("content_sha256", "A" * 64),
        ("retrieved_on", "2027-02-30"),
        ("format", "txt"),
        ("page_state", "verified"),
    ],
)
def test_invalid_source_metadata(key: str, value: str) -> None:
    data = example()["source"]
    data[key] = value
    with pytest.raises(ValidationError):
        Source.model_validate(data)


@pytest.mark.parametrize("value", [{"value": 3.0}, {"value": "3.0", "scale": 4.0}])
def test_gpa_shape_is_not_repaired(value: Any) -> None:
    data = example()["conditions"][0]
    data["value"] = value
    with pytest.raises(ValidationError):
        TypeAdapter(Condition).validate_python(data)


@pytest.mark.parametrize(
    "value",
    [
        {"options": []},
        {"logic": "or", "options": []},
        {"logic": "any", "options": []},
        {"logic": "any", "options": [{"test": "Test"}]},
    ],
)
def test_invalid_language_shapes(value: Any) -> None:
    with pytest.raises(ValidationError):
        LanguageValue.model_validate(value)


def test_language_and_funding_optional_shapes() -> None:
    language = LanguageValue.model_validate(
        {
            "logic": "all",
            "options": [{"test": "Fictional test", "min_overall": 7, "min_subscore": 6}],
        }
    )
    assert language.options[0].min_subscore == 6
    funding = FundingCoverage(item="travel", amount_max=100, currency="EUR", period="one_time")
    assert funding.amount_max == 100


@pytest.mark.parametrize("change", [{"kind": "unknown"}, {"evidence": []}])
def test_invalid_conditions(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Condition).validate_python({**example()["conditions"][0], **change})


@pytest.mark.parametrize(
    "change",
    [
        {"date": "2027-02-30"},
        {"time": "25:00"},
        {"type": "funding"},
        {"status": "verified"},
        {"cycle_year": "2027"},
        {"rolling": "yes"},
    ],
)
def test_deadline_structural_errors(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Deadline.model_validate({**example()["deadlines"][0], **change})


def test_deadline_cross_field_rules_are_enforced_by_issue_17() -> None:
    data = {**example()["deadlines"][0], "rolling": True, "timezone": None}
    with pytest.raises(ValidationError):
        Deadline.model_validate(data)
    valid = example()["deadlines"][0]
    with pytest.raises(ValidationError, match="exact duplicate deadline"):
        from_gold_label({**example(), "deadlines": [valid, valid]})


def test_extractor_metadata_and_unknown_keys() -> None:
    record = from_gold_label({**example(), "model": "fictional-model", "prompt_version": "p1"})
    assert record.model == "fictional-model" and record.prompt_version == "p1"
    with pytest.raises(ValidationError):
        RequirementRecord.model_validate({**record.model_dump(), "unexpected": True})


def test_generated_issue_16_acceptance_comes_from_updated_plan() -> None:
    spec = importlib.util.spec_from_file_location("issue_plan", ROOT / "scripts/create_issues.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    issues = [
        (ms, issue)
        for ms in module.parse_plan(ROOT / "docs/05-milestones-and-issues.md")
        for issue in ms["issues"]
        if issue["title"] == "Pydantic schema for Requirement Record"
    ]
    assert len(issues) == 1
    body = module.child_body(*issues[0])
    assert "verification" in body and "usable_for_logic" in body and "evidence" in body
