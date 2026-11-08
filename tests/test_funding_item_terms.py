"""English category-presence controls with fictional quotes and FakeClient only."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, get_args

import pytest
from test_extractor import field, payload
from test_first_run_fixes import run_cli
from test_llm import request
from test_numeric_provenance import funding, pipeline

from scholarscope.extraction import PROMPT_VERSIONS
from scholarscope.extraction.convert import convert_group
from scholarscope.extraction.guards import FUNDING_ITEM_TERMS, funding_item_term_error
from scholarscope.extraction.wire import FundingGroup
from scholarscope.llm.base import StructuredRequest
from scholarscope.llm.cache import cache_key
from scholarscope.llm.fake import FakeClient
from scholarscope.schema import FundingCoverage


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("live sockets prohibited in item-term tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "fake-v1")


def entry(item: str, **changes: Any) -> dict[str, Any]:
    return {**funding(), "item": item, **changes}


def test_lexicon_covers_the_canonical_literal_without_forbidden_terms() -> None:
    vocabulary = set(get_args(FundingCoverage.model_fields["item"].annotation))
    assert set(FUNDING_ITEM_TERMS) == vocabulary - {"other"}
    assert all(terms and all(terms) for terms in FUNDING_ITEM_TERMS.values())
    assert not (
        {"residence", "stay", "permit", "grant"}
        & {term for terms in FUNDING_ITEM_TERMS.values() for term in terms}
    )


@pytest.mark.parametrize(
    "item,term", [(item, term) for item, terms in FUNDING_ITEM_TERMS.items() for term in terms]
)
def test_every_documented_term_matches_original_quote_at_word_start(item: str, term: str) -> None:
    assert funding_item_term_error(item, (f"Example award covers {term} costs.",)) is None


def test_multiple_fictional_costs_keep_visa_and_insurance_but_reject_housing() -> None:
    quote = "Example award pays for a visa, a residence permit, and two forms of insurance."
    bad = entry("housing", note="PRIVATE_FICTIONAL_ITEM", fictional_extra="original raw item")
    result = pipeline(funded=[entry("visa"), bad, entry("insurance")], funding_quotes=(quote,))
    assert result.record and result.extraction
    kept = result.record.fields.funding_coverage.value
    assert kept and [item.item for item in kept] == ["visa", "insurance"]
    assert result.extraction.group_status["funding"] == "partial"
    assert not result.extraction.failed_groups
    assert len(result.extraction.rejected_items) == 1
    rejected = result.extraction.rejected_items[0]
    assert (rejected.group, rejected.index, rejected.reason) == (
        "funding",
        1,
        "ITEM_TERM_NOT_IN_QUOTE:housing",
    )
    assert rejected.raw_item == bad
    assert "PRIVATE_FICTIONAL_ITEM" not in result.record.model_dump_json()


@pytest.mark.parametrize(
    "quote,accepted",
    [
        ("Example award offers free accommodation in a student dormitory.", True),
        ("Example award offers FREE ACCOMMODATION IN A STUDENT DORMITORY.", True),
        ("Example award provides rental assistance.", True),
        ("Example award provides current assistance.", False),
        ("Example award provides room and board.", True),
        ("Example award provides room  and board.", False),
    ],
)
def test_housing_original_quote_case_and_word_start_rules(quote: str, accepted: bool) -> None:
    result = pipeline(funded=[entry("housing")], funding_quotes=(quote,))
    assert result.record and result.extraction
    assert bool(result.extraction.rejected_items) is not accepted
    if accepted:
        assert result.record.fields.funding_coverage.value
    else:
        assert result.extraction.rejected_items[0].reason == "ITEM_TERM_NOT_IN_QUOTE:housing"


def test_terms_are_not_borrowed_from_uncited_source_text_or_joined_across_quotes() -> None:
    result = pipeline(
        funded=[entry("housing")],
        funding_quotes=("Example award pays permit costs.",),
        extra_text="Example housing is described elsewhere.",
    )
    assert result.extraction
    assert result.extraction.rejected_items[0].reason == "ITEM_TERM_NOT_IN_QUOTE:housing"
    assert funding_item_term_error("housing", ("Example room", "and board")) == (
        "ITEM_TERM_NOT_IN_QUOTE:housing"
    )


def test_term_in_second_field_quote_qualifies() -> None:
    result = pipeline(
        funded=[entry("housing")],
        funding_quotes=(
            "Example award supports several costs.",
            "Example lodging costs are included.",
        ),
    )
    assert result.record and result.extraction and not result.extraction.rejected_items
    assert result.record.fields.funding_coverage.verification == "verified"


@pytest.mark.parametrize(
    "quotes",
    [
        (),
        ("Example grant covers residence, stay and permit.",),
        ("Exemple: soutien pour fournitures.",),
    ],
)
def test_other_always_bypasses_only_the_term_guard(quotes: tuple[str, ...]) -> None:
    assert funding_item_term_error("other", quotes) is None


def test_non_english_item_is_rejected_and_reported_while_other_survives() -> None:
    quote = "Exemple: bourse pour frais d'inscription."
    result = pipeline(funded=[entry("tuition"), entry("other")], funding_quotes=(quote,))
    assert result.record and result.extraction
    assert [r.reason for r in result.extraction.rejected_items] == [
        "ITEM_TERM_NOT_IN_QUOTE:tuition"
    ]
    kept = result.record.fields.funding_coverage.value
    assert kept and [item.item for item in kept] == ["other"]


def test_all_rejections_keep_absent_field_rejection_note_and_group_failure_marker() -> None:
    quote = "Example award supports permit costs."
    bad = entry("housing")
    original = {"funding_coverage": field([bad], quote, "p-fictional")}
    untouched = deepcopy(original)
    draft: dict[str, Any] = {"fields": {}, "notes": None}
    rejections = convert_group(
        "funding",
        FundingGroup.model_validate(original).model_dump(),
        draft,
        original=original,
        sent_passages=(("p-fictional", quote),),
    )
    assert original == untouched
    assert len(rejections) == 1 and rejections[0].raw_item == bad
    assert draft["fields"]["funding_coverage"]["status"] == "absent"
    assert (
        draft["fields"]["funding_coverage"]["notes"]
        == "EXTRACTION_REJECTED:funding:funding_coverage"
    )
    result = pipeline(funded=[bad], funding_quotes=(quote,))
    assert result.record and result.extraction and result.extraction.failed_groups == ("funding",)
    rejected_field = result.record.fields.funding_coverage
    assert rejected_field.status == "absent" and rejected_field.value is None
    assert rejected_field.notes == (
        "EXTRACTION_FAILED:funding:invalid_output\nEXTRACTION_REJECTED:funding:funding_coverage"
    )


def test_numeric_then_item_term_then_domain_first_failure_wins() -> None:
    numeric = pipeline(funded=[entry("housing", amount=800.0)])
    assert numeric.extraction
    assert [r.reason for r in numeric.extraction.rejected_items] == ["NUMBER_NOT_IN_QUOTE:amount"]
    assert numeric.record and "EXTRACTION_REJECTED:funding:funding_coverage" in (
        numeric.record.fields.funding_coverage.notes or ""
    )
    term = pipeline(funded=[entry("housing")])  # Also lacks required field evidence.
    assert term.extraction
    assert [r.reason for r in term.extraction.rejected_items] == ["ITEM_TERM_NOT_IN_QUOTE:housing"]
    domain = pipeline(funded=[entry("other")])
    assert domain.extraction
    assert len(domain.extraction.rejected_items) == 1
    assert (
        "present requires at least one evidence quote" in domain.extraction.rejected_items[0].reason
    )


@pytest.mark.parametrize("show", [False, True])
def test_rejected_item_console_raw_data_remains_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], show: bool
) -> None:
    marker = "PRIVATE_FICTIONAL_ITEM"

    def respond(req: StructuredRequest[Any]) -> str:
        answer = payload(req)
        if req.prompt_version.startswith("funding-"):
            answer = {
                "funding_coverage": field(
                    [entry("housing", note=marker)],
                    "Example permit costs are included.",
                    req.untrusted_passages[0][0],
                )
            }
        return json.dumps(answer)

    client = FakeClient(responses=[respond] * 5)
    record, summary = run_cli(
        tmp_path, monkeypatch, capsys, client, *(("--show-rejected",) if show else ())
    )
    assert summary["rejected_items"] == 1
    rejection = summary["rejected_item_details"][0]
    assert (rejection["group"], rejection["index"], rejection["reason"]) == (
        "funding",
        0,
        "ITEM_TERM_NOT_IN_QUOTE:housing",
    )
    assert ("raw_item" in rejection) is show
    assert (marker in json.dumps(summary)) is show
    assert marker not in json.dumps(record)


def test_funding_v4_version_task_and_cache_invalidation() -> None:
    folder = Path(__file__).resolve().parents[1] / "scholarscope/extraction/prompts"
    old_task = (folder / "funding.v3.txt").read_text(encoding="utf-8")
    new_task = (folder / "funding.v4.txt").read_text(encoding="utf-8")
    assert PROMPT_VERSIONS["funding"] == "funding-v4" and old_task != new_task
    before = request(task=old_task, prompt_version="funding-v3")
    key = cache_key("fake", "fictional", before)
    assert cache_key("fake", "fictional", replace(before, prompt_version="funding-v4")) != key
    assert cache_key("fake", "fictional", replace(before, task=new_task)) != key
    assert "Create a funding item only when the quote names that kind of cost" in new_task
    assert "Each item's note is the shortest wording from the quote" in new_task
