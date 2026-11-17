"""Fictional item diagnostics only; no real label text or provider calls."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_eval import program
from test_evidence_matched import condition

from scholarscope.eval.metrics import ProgramEvaluation
from scholarscope.eval.report import build_report, markdown, write_report
from scholarscope.extraction.convert import RejectedItem
from scholarscope.schema import Evidence, FundingCoverage

MODES = ("strict", "evidence-matched")
FAMILIES = ("conditions", "funding_coverage", "deadlines")
QUOTE = "Fictional micro-\nscope\u200b applicants <script>pause</script>  must register."
NORMALIZED = "Fictional microscope applicants <script>pause</script> must register."
LOCATOR = "Fictional table | A"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("network forbidden in unmatched-item tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket, "getaddrinfo", fail)


def report_for(p: list[ProgramEvaluation]) -> dict[str, Any]:
    return build_report(p, [], date="2026-11-16", git_commit="fictional")


def entries(report: dict[str, Any], mode: str, family: str) -> dict[str, Any]:
    return report["scoring_modes"][mode]["programs"][0]["item_diagnostics"][family]


def items(p: ProgramEvaluation, family: str) -> list[Any]:
    if family == "funding_coverage":
        return p.gold.record.fields.funding_coverage.value or []
    return getattr(p.gold.record, family)


def changed(
    p: ProgramEvaluation, family: str, gold: list[Any], predicted: list[Any]
) -> ProgramEvaluation:
    assert p.pipeline.record
    g, r = p.gold.record.model_copy(deep=True), p.pipeline.record.model_copy(deep=True)
    if family == "funding_coverage":
        for record, values in ((g, gold), (r, predicted)):
            field = record.fields.funding_coverage
            field.value = values or None
            field.status = "present" if values else "absent"
            field.evidence = [Evidence(quote=QUOTE, locator=LOCATOR)] if values else []
    else:
        setattr(g, family, gold)
        setattr(r, family, predicted)
        if family == "deadlines":
            g.deadlines_status = "present" if gold else "absent"
            r.deadlines_status = "present" if predicted else "absent"
    return replace(p, gold=replace(p.gold, record=g), pipeline=replace(p.pipeline, record=r))


def extra(p: ProgramEvaluation, family: str) -> Any:
    evidence = [Evidence(quote=QUOTE, locator=LOCATOR)]
    if family == "conditions":
        return condition(QUOTE).model_copy(update={"evidence": evidence})
    if family == "funding_coverage":
        return FundingCoverage(item="visa", note="Fictional permit processing")
    return p.gold.record.deadlines[0].model_copy(update={"type": "other", "evidence": evidence})


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("family", FAMILIES)
def test_missed_gold_retains_original_index_normalized_quote_and_locator(
    tmp_path: Path, mode: str, family: str
) -> None:
    p = program(tmp_path)
    originals = items(p, family)
    p = changed(p, family, [*originals, extra(p, family)], originals)
    data = entries(report_for([p]), mode, family)
    assert [i["index"] for i in data["missed_gold_items"]] == [1]
    assert data["missed_gold_items"][0]["evidence"] == [{"quote": NORMALIZED, "locator": LOCATOR}]
    assert not data["unmatched_predicted_items"] and not data["excluded"]
    category = {"conditions": "kind", "funding_coverage": "item", "deadlines": "type"}[family]
    assert data["missed_gold_items"][0][category] == getattr(extra(p, family), category)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("family", FAMILIES)
def test_unmatched_prediction_includes_verification_even_when_unverified(
    tmp_path: Path, mode: str, family: str
) -> None:
    p = program(tmp_path)
    originals, new = items(p, family), extra(p, family)
    if family != "funding_coverage":
        new = new.model_copy(update={"verification": "unverified"})
    p = changed(p, family, originals, [*originals, new])
    assert p.pipeline.record
    p.pipeline.record.fields.funding_coverage.verification = "unverified"
    data = entries(report_for([p]), mode, family)
    assert [i["index"] for i in data["unmatched_predicted_items"]] == [1]
    item = data["unmatched_predicted_items"][0]
    assert item["verification"] == "unverified"
    assert item["evidence"] == [{"quote": NORMALIZED, "locator": LOCATOR}]
    assert item["reason"] == ("multiset_difference" if mode == "strict" else "no_pair")
    assert not data["missed_gold_items"]


@pytest.mark.parametrize("mode", MODES)
def test_equal_items_never_appear(tmp_path: Path, mode: str) -> None:
    r = report_for([program(tmp_path)])
    for family in FAMILIES:
        assert not entries(r, mode, family)["missed_gold_items"]
        assert not entries(r, mode, family)["unmatched_predicted_items"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("family", FAMILIES)
def test_structured_disagreement_lists_both_sides_and_existing_pair(
    tmp_path: Path, mode: str, family: str
) -> None:
    p = program(tmp_path)
    original = extra(p, family)
    updates = {
        "conditions": {"kind": "degree_held"},
        "funding_coverage": {"amount": 123},
        "deadlines": {"type": "document"},
    }[family]
    p = changed(p, family, [original], [original.model_copy(update=updates)])
    data = entries(report_for([p]), mode, family)
    for key in ("missed_gold_items", "unmatched_predicted_items"):
        assert len(data[key]) == 1
        assert data[key][0]["index"] == 0
        assert data[key][0]["reason"] == (
            "multiset_difference" if mode == "strict" else "structured_disagreement"
        )
        assert data[key][0]["paired_index"] == (None if mode == "strict" else 0)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("family", FAMILIES)
def test_duplicate_multiplicity_consumes_lowest_indices(
    tmp_path: Path, mode: str, family: str
) -> None:
    p = program(tmp_path)
    item = extra(p, family)
    p = changed(p, family, [item, item, item], [item])
    data = entries(report_for([p]), mode, family)
    assert [i["index"] for i in data["missed_gold_items"]] == [1, 2]
    assert not data["unmatched_predicted_items"]
    p = changed(p, family, [item], [item, item, item])
    data = entries(report_for([p]), mode, family)
    assert [i["index"] for i in data["unmatched_predicted_items"]] == [1, 2]


def test_text_only_differences_are_not_evidence_matched_misses(tmp_path: Path) -> None:
    p = program(tmp_path)
    original = condition()
    p = changed(p, "conditions", [original], [condition(value="Fictional paraphrase")])
    assert entries(report_for([p]), "strict", "conditions")["missed_gold_items"]
    assert not entries(report_for([p]), "evidence-matched", "conditions")["missed_gold_items"]
    funding = FundingCoverage(item="stipend", note="Fictional short wording")
    p = changed(
        p, "funding_coverage", [funding], [funding.model_copy(update={"note": "Alternate"})]
    )
    assert entries(report_for([p]), "strict", "funding_coverage")["unmatched_predicted_items"]
    assert not entries(report_for([p]), "evidence-matched", "funding_coverage")[
        "unmatched_predicted_items"
    ]


@pytest.mark.parametrize("rejected", [False, True])
@pytest.mark.parametrize("family", FAMILIES)
def test_excluded_families_are_flagged_not_reported_as_misses(
    tmp_path: Path, rejected: bool, family: str
) -> None:
    p = program(tmp_path)
    assert p.pipeline.extraction
    group = "funding" if family == "funding_coverage" else family
    extraction = replace(
        p.pipeline.extraction,
        **(
            {
                "rejected_items": (
                    RejectedItem(
                        group, "funding_coverage" if group == "funding" else 0, "fictional", {}
                    ),
                )
            }
            if rejected
            else {"failed_groups": (group,)}
        ),
    )
    p = replace(p, pipeline=replace(p.pipeline, extraction=extraction))
    for mode in MODES:
        data = entries(report_for([p]), mode, family)
        assert data["excluded"]
        assert not data["missed_gold_items"] and not data["unmatched_predicted_items"]


def test_json_markdown_privacy_escaping_section_order_and_program_order(tmp_path: Path) -> None:
    p = program(tmp_path)
    p = changed(p, "conditions", [extra(p, "conditions")], [])
    other = replace(p, gold=replace(p.gold, slug="fictional-zeta"))
    r = report_for([other, p])
    assert json.dumps(r, sort_keys=True) == json.dumps(report_for([p, other]), sort_keys=True)
    assert r["report_version"] == "4"
    target = tmp_path / "private.json"
    write_report(r, [p, other], target)
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert (
        entries(stored, "strict", "conditions")["missed_gold_items"][0]["evidence"][0]["quote"]
        == NORMALIZED
    )
    text = markdown(r)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "Missed gold items" in text and "Unmatched predicted items" in text
    assert text.index("## strict — missed gold") > text.index("## Dangerous verified-value errors")
    assert text.index("## evidence-matched — missed gold") > text.index(
        "## Evidence-matched dangerous errors"
    )
