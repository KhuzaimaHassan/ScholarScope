"""Fictional evidence and scripted fixtures only; no real labels or inference."""

from __future__ import annotations

import hashlib
import json
import random
import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_eval import program

from scholarscope.eval.evidence_matched import (
    IndexedItem,
    aggregate_evidence_matched,
    normalize_document,
    pair_funding_items,
    pair_items,
    score_evidence_matched,
)
from scholarscope.eval.metrics import ProgramEvaluation, aggregate, score_program
from scholarscope.eval.report import build_report, markdown
from scholarscope.extraction.convert import RejectedItem
from scholarscope.schema import Evidence, FundingCoverage, OtherCondition

ROOT = Path(__file__).resolve().parents[1]
QUOTE = "Example applicants must register for full-time study."


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("network forbidden in evidence-matched tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket, "getaddrinfo", fail)


def condition(
    quote: str = QUOTE,
    *,
    kind: Any = "other",
    value: Any = "Registered full time",
    verified: bool = True,
) -> OtherCondition:
    return OtherCondition(
        kind=kind,
        value=value,
        required=True,
        applies_to=None,
        evidence=[Evidence(quote=quote)],
        verification="verified" if verified else "unverified",
    )


def indexed(index: int, quote: str = QUOTE, **kwargs: Any) -> IndexedItem:
    value = condition(quote, **kwargs)
    return IndexedItem(index, value, (quote,), value.verification == "verified")


def with_conditions(
    p: ProgramEvaluation, gold: list[Any], predicted: list[Any]
) -> ProgramEvaluation:
    assert p.pipeline.record is not None
    g, r = p.gold.record.model_copy(deep=True), p.pipeline.record.model_copy(deep=True)
    g.conditions, r.conditions = gold, predicted
    return replace(p, gold=replace(p.gold, record=g), pipeline=replace(p.pipeline, record=r))


def summary(p: ProgramEvaluation) -> dict[str, Any]:
    return aggregate_evidence_matched([score_evidence_matched(p)])


def strict_cases(tmp_path: Path) -> dict[str, ProgramEvaluation]:
    p = program(tmp_path)
    assert p.pipeline.record and p.pipeline.extraction
    wrong = p.pipeline.record.model_copy(deep=True)
    wrong.fields.program_name.value = "Fictional Harbour Fellowship"
    text = p.pipeline.record.model_copy(deep=True)
    text.fields.required_documents.value = ["The TRANSCRIPT"]
    assert text.fields.funding_coverage.value
    text.fields.funding_coverage.value[0].note = "Fictional payment wording"
    return {
        "perfect": p,
        "wrong_name": replace(p, pipeline=replace(p.pipeline, record=wrong)),
        "text_differences": replace(p, pipeline=replace(p.pipeline, record=text)),
        "failed_funding": replace(
            p,
            pipeline=replace(
                p.pipeline, extraction=replace(p.pipeline.extraction, failed_groups=("funding",))
            ),
        ),
        "rejected_conditions": replace(
            p,
            pipeline=replace(
                p.pipeline,
                extraction=replace(
                    p.pipeline.extraction,
                    rejected_items=(RejectedItem("conditions", 0, "fictional-rejection", {}),),
                ),
            ),
        ),
    }


def strict_numbers(p: ProgramEvaluation) -> dict[str, Any]:
    def numeric_tree(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: numeric_tree(child)
                for key, child in value.items()
                if key
                not in {"dangerous_errors", "failed_groups", "rejected_items", "verifier_bugs"}
                and not isinstance(child, str)
            }
        if isinstance(value, list):
            return [numeric_tree(child) for child in value if not isinstance(child, str)]
        return value

    return numeric_tree(aggregate([score_program(p)]))


def test_strict_numbers_byte_identical_to_pre_change_fixtures(tmp_path: Path) -> None:
    frozen = json.loads(
        (ROOT / "tests/fixtures/strict-evaluation-numbers.json").read_text(encoding="utf-8")
    )
    source = (ROOT / "scholarscope/eval/metrics.py").read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == frozen["strict_source_sha256"]
    for name, p in strict_cases(tmp_path).items():
        before = json.dumps(frozen["cases"][name], sort_keys=True, separators=(",", ":")).encode()
        current = json.dumps(strict_numbers(p), sort_keys=True, separators=(",", ":")).encode()
        assert current == before
        report = build_report([p], [], date="2026-11-11", git_commit="fictional")
        assert (
            report["scoring_modes"]["strict"]["overall"]
            == report["overall"]
            == aggregate([score_program(p)])
        )
        assert report["scoring_modes"]["strict"]["programs"] == report["programs"]


def test_same_quote_paraphrased_condition_value_pairs(tmp_path: Path) -> None:
    p = with_conditions(
        program(tmp_path),
        [condition(value="Full-time enrolment")],
        [condition(value="Registered full time")],
    )
    result = summary(p)
    assert result["per_field"]["conditions"]["tp"] == 1
    assert not result["dangerous_errors"]
    assert result["per_field"]["conditions"]["advisory_text_agreement"] == {
        "compared": 1,
        "equal": 0,
        "different": 1,
        "rate": 0.0,
    }
    assert score_program(p)["dangerous_errors"]


@pytest.mark.parametrize(
    "quote",
    ["Ｅxample regis-\ntration", "Example\u00ad regis\u200btration", "Example   registration"],
)
def test_pairing_reuses_presence_oracle_formatting(quote: str) -> None:
    assert pair_items([indexed(0, "Example registration")], [indexed(0, quote)])


@pytest.mark.parametrize(
    "quote", ["Example applicants register for part-time study.", QUOTE.upper(), "\u200b\u00ad"]
)
def test_no_token_similarity_case_fold_or_empty_quote_pairing(quote: str) -> None:
    assert not pair_items([indexed(0)], [indexed(0, quote)])


def test_greedy_priority_and_shuffled_indexed_input_are_deterministic() -> None:
    gold = [indexed(0), indexed(1, kind="residency"), indexed(2, "Example distant clause.")]
    predicted = [
        indexed(0, kind="residency"),
        indexed(1),
        indexed(2, "Example distant clause. Extra text."),
    ]
    expected = pair_items(gold, predicted)
    assert {(p.gold_index, p.predicted_index) for p in expected} == {(1, 0), (0, 1), (2, 2)}
    for seed in range(25):
        rng = random.Random(seed)
        g, p = gold.copy(), predicted.copy()
        rng.shuffle(g)
        rng.shuffle(p)
        assert pair_items(g, p) == expected
    # Exact equality wins over a lower prediction index with containing evidence.
    assert (
        pair_items([indexed(0)], [indexed(0, QUOTE + " Extra."), indexed(1)])[0].predicted_index
        == 1
    )


def test_longest_containment_then_indices_and_one_to_one(tmp_path: Path) -> None:
    small, large = "Example first clause.", "Example second clause has more words."
    p = with_conditions(
        program(tmp_path), [condition(small), condition(large)], [condition(small + " " + large)]
    )
    scored = score_evidence_matched(p)
    assert scored["pairings"]["conditions"][0]["gold_index"] == 1
    assert scored["fields"]["conditions"]["tp"] == 1
    assert scored["fields"]["conditions"]["fn"] == 1
    assert len(scored["pairings"]["conditions"]) == 1
    ties = pair_items([indexed(3), indexed(1)], [indexed(8), indexed(2)])
    assert [(pair.gold_index, pair.predicted_index) for pair in ties] == [(1, 2), (3, 8)]


@pytest.mark.parametrize("predicted", ["a transcript", "AN  TRANSCRIPT", " the\ttranscript "])
def test_articles_case_and_whitespace_only_in_new_mode(tmp_path: Path, predicted: str) -> None:
    p = program(tmp_path)
    assert p.pipeline.record
    record = p.pipeline.record.model_copy(deep=True)
    record.fields.required_documents.value = [predicted]
    p = replace(p, pipeline=replace(p.pipeline, record=record))
    assert summary(p)["per_field"]["required_documents"]["tp"] == 1
    assert score_program(p)["fields"]["required_documents"]["fp"] == 1
    assert normalize_document("theory") == "theory"


def test_funding_note_only_difference_is_advisory(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record and p.pipeline.record.fields.funding_coverage.value
    p.pipeline.record.fields.funding_coverage.value[0].note = "Fictional living payment wording"
    result = summary(p)
    assert not result["dangerous_errors"]
    assert result["per_field"]["funding_coverage"]["tp"] == 1
    assert result["per_field"]["funding_coverage"]["advisory_text_agreement"]["different"] == 1
    assert score_program(p)["fields"]["funding_coverage"]["fp"] == 1


def test_named_field_notes_are_advisory_not_errors(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record
    p.pipeline.record.fields.funding_coverage.notes = "Example annotation, not a funding value."
    result = summary(p)
    assert not result["dangerous_errors"]
    assert result["per_field"]["funding_coverage"]["advisory_text_agreement"]["different"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": 501},
        {"amount_max": 600},
        {"currency": "EUR"},
        {"period": "year"},
    ],
)
def test_funding_structured_fields_remain_exact(tmp_path: Path, changes: dict[str, Any]) -> None:
    p = program(tmp_path)
    assert p.pipeline.record and p.pipeline.record.fields.funding_coverage.value
    item = p.pipeline.record.fields.funding_coverage.value[0]
    p.pipeline.record.fields.funding_coverage.value[0] = item.model_copy(update=changes)
    result = summary(p)
    assert (
        result["per_field"]["funding_coverage"]["fp"]
        == result["per_field"]["funding_coverage"]["fn"]
        == 1
    )
    assert len(result["dangerous_errors"]) == len(result["other_structured_disagreements"]) == 1


def test_applies_to_wording_is_advisory_but_presence_is_structured(tmp_path: Path) -> None:
    gold, predicted = condition(), condition()
    gold.applies_to, predicted.applies_to = (
        "Example returning students",
        "Example continuing cohort",
    )
    p = with_conditions(program(tmp_path), [gold], [predicted])
    assert not summary(p)["dangerous_errors"]
    predicted.applies_to = None
    result = summary(p)
    assert result["dangerous_errors"][0]["disagreements"][0]["field"] == "applies_to_presence"


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"date": "2027-05-02"}, "date"),
        ({"type": "scholarship"}, "type"),
        ({"time": "22:59"}, "time"),
        ({"timezone": "UTC+02:00"}, "timezone"),
    ],
)
def test_paired_deadline_structured_disagreement_is_dangerous(
    tmp_path: Path, changes: dict[str, Any], field: str
) -> None:
    p = program(tmp_path)
    assert p.pipeline.record
    p.pipeline.record.deadlines[0] = p.pipeline.record.deadlines[0].model_copy(update=changes)
    result = summary(p)
    assert result["deadlines"]["fp"] == result["deadlines"]["fn"] == 1
    assert len(result["other_structured_disagreements"]) == 1
    assert not result["kind_disagreements"]
    assert result["dangerous_errors"][0]["disagreements"][0]["field"] == field


@pytest.mark.parametrize("also_required", [False, True])
def test_kind_disagreement_separate_from_other_structured_errors(
    tmp_path: Path, also_required: bool
) -> None:
    predicted = condition(kind="residency")
    if also_required:
        predicted.required = False
    result = summary(with_conditions(program(tmp_path), [condition()], [predicted]))
    assert len(result["dangerous_errors"]) == len(result["kind_disagreements"]) == 1
    assert len(result["other_structured_disagreements"]) == int(also_required)


@pytest.mark.parametrize("verified", [False, True])
def test_unpaired_predicted_counts_fp_and_only_verified_is_dangerous(
    tmp_path: Path, verified: bool
) -> None:
    p = with_conditions(
        program(tmp_path),
        [condition()],
        [condition("Example unmatched quotation.", verified=verified)],
    )
    result = summary(p)
    assert result["per_field"]["conditions"]["fp"] == result["per_field"]["conditions"]["fn"] == 1
    assert (
        len(result["dangerous_errors"]) == len(result["unpaired_verified_items"]) == int(verified)
    )


@pytest.mark.parametrize("group", ["identity", "funding", "documents", "deadlines", "conditions"])
def test_failed_group_exclusions_unchanged(tmp_path: Path, group: str) -> None:
    p = program(tmp_path)
    assert p.pipeline.extraction
    p = replace(
        p,
        pipeline=replace(
            p.pipeline, extraction=replace(p.pipeline.extraction, failed_groups=(group,))
        ),
    )
    strict, matched = score_program(p), score_evidence_matched(p)
    for name, old in strict["fields"].items():
        assert matched["fields"][name]["excluded"] == old["excluded"]
        if old["excluded"]:
            assert (
                matched["fields"][name]["tp"]
                == matched["fields"][name]["fp"]
                == matched["fields"][name]["fn"]
                == 0
            )
    assert matched["deadlines"]["excluded"] == strict["deadlines"]["excluded"]


@pytest.mark.parametrize(
    "group,index",
    [("conditions", 0), ("deadlines", 0), ("funding", 0), ("identity", "institution")],
)
def test_rejected_exclusions_unchanged(tmp_path: Path, group: str, index: Any) -> None:
    p = program(tmp_path)
    assert p.pipeline.extraction
    p = replace(
        p,
        pipeline=replace(
            p.pipeline,
            extraction=replace(
                p.pipeline.extraction, rejected_items=(RejectedItem(group, index, "fictional", {}),)
            ),
        ),
    )
    strict, matched = score_program(p), score_evidence_matched(p)
    for name, old in strict["fields"].items():
        assert matched["fields"][name]["excluded"] == old["excluded"]
    assert matched["deadlines"]["excluded"] == strict["deadlines"]["excluded"]
    assert matched["rejected_items"] == strict["rejected_items"]


def test_reports_label_both_modes_and_keep_original_sections(tmp_path: Path) -> None:
    p = program(tmp_path)
    report = build_report([p], [], date="2026-11-11", git_commit="fictional")
    assert report["report_version"] == "3"
    rendered = markdown(report)
    for text in (
        "strict",
        "evidence-matched",
        "Advisory text agreement",
        "Kind disagreements",
        "Other structured disagreements",
        "EXTRACTION FAILED",
        "VERIFIER BUGS",
        "Labels skipped",
    ):
        assert text in rendered


def test_verified_duplicate_cannot_reuse_a_gold_item(tmp_path: Path) -> None:
    p = with_conditions(program(tmp_path), [condition()], [condition(), condition()])
    result = summary(p)
    counts = result["per_field"]["conditions"]
    assert (counts["tp"], counts["fp"], counts["fn"]) == (1, 1, 0)
    assert result["unpaired_verified_items"][0]["predicted_index"] == 1
    assert result["error_counts"]["unpaired_verified"] == 1


def test_reordered_funding_items_with_shared_evidence_pair_correctly(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record
    gold = p.gold.record.model_copy(deep=True)
    prediction = p.pipeline.record.model_copy(deep=True)
    values = [FundingCoverage(item=item) for item in ("tuition", "visa", "other", "insurance")]
    gold.fields.funding_coverage.value = values
    prediction.fields.funding_coverage.value = [values[i].model_copy() for i in (0, 1, 3, 2)]
    # Existing field-level quotes are the same for every item on each side.
    p = replace(
        p, gold=replace(p.gold, record=gold), pipeline=replace(p.pipeline, record=prediction)
    )
    scored = score_evidence_matched(p)
    assert [
        (pair["gold_index"], pair["predicted_index"])
        for pair in scored["pairings"]["funding_coverage"]
    ] == [(0, 0), (1, 1), (2, 3), (3, 2)]
    assert scored["fields"]["funding_coverage"]["tp"] == 4
    assert not scored["dangerous_errors"]
    assert all(
        pair["pairing_rule"] == "exact_normalized_item" and "exact_quote" not in pair
        for pair in scored["pairings"]["funding_coverage"]
    )


def test_funding_duplicates_pair_in_index_order_without_reading_quotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any) -> Any:
        pytest.fail("funding pairing must not normalize or compare quotes")

    monkeypatch.setattr("scholarscope.eval.evidence_matched.quote_normalize", forbidden)
    a = FundingCoverage(item="other", amount=1)
    b = FundingCoverage(item="other", amount=2)
    gold = [IndexedItem(8, a, ("Shared example evidence",)), IndexedItem(2, b, ())]
    predicted = [IndexedItem(9, b, ("Unrelated example",)), IndexedItem(3, a, ())]
    expected = pair_funding_items(gold, predicted)
    assert [(pair.gold_index, pair.predicted_index) for pair in expected] == [(2, 3), (8, 9)]
    assert pair_funding_items(list(reversed(gold)), list(reversed(predicted))) == expected


@pytest.mark.parametrize("verified", [False, True])
def test_funding_item_absent_from_gold_is_unpaired(tmp_path: Path, verified: bool) -> None:
    p = program(tmp_path)
    assert p.pipeline.record and p.pipeline.record.fields.funding_coverage.value
    value = p.pipeline.record.fields.funding_coverage.value[0]
    p.pipeline.record.fields.funding_coverage.value[0] = value.model_copy(
        update={"item": "housing"}
    )
    p.pipeline.record.fields.funding_coverage.verification = (
        "verified" if verified else "unverified"
    )
    result = summary(p)
    counts = result["per_field"]["funding_coverage"]
    assert (counts["tp"], counts["fp"], counts["fn"]) == (0, 1, 1)
    assert len(result["unpaired_verified_items"]) == int(verified)
    assert not result["other_structured_disagreements"]
    if verified:
        assert result["unpaired_verified_items"][0]["gold_index"] is None


def test_funding_item_normalization_is_exact_without_case_folding() -> None:
    gold = IndexedItem(0, FundingCoverage(item="other"), ())
    value = FundingCoverage(item="other")
    assert pair_funding_items(
        [gold], [IndexedItem(0, value.model_copy(update={"item": "  other  "}), ())]
    )
    assert not pair_funding_items(
        [gold], [IndexedItem(0, value.model_copy(update={"item": "Other"}), ())]
    )


def test_right_quote_wrong_free_text_value_is_a_documented_limit(tmp_path: Path) -> None:
    p = with_conditions(
        program(tmp_path),
        [condition(value="Full-time registration")],
        [condition(value="An unrelated fictional assertion")],
    )
    result = summary(p)
    assert result["per_field"]["conditions"]["tp"] == 1
    assert not result["dangerous_errors"]
    assert result["per_field"]["conditions"]["advisory_text_agreement"]["different"] == 1


def test_nonempty_containment_has_no_minimum_quote_length() -> None:
    pairs = pair_items([indexed(0, "A")], [indexed(0, "An unrelated example sentence.")])
    assert len(pairs) == 1 and pairs[0].overlap_length == 1
