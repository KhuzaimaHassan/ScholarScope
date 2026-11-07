"""Fictional quotes and scripted wire outputs only; no live page/model calls."""

from __future__ import annotations

import html
import json
import socket
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_extractor import content, deadline, fetch, field, payload
from test_llm import request

from scholarscope.extraction import PROMPT_VERSIONS
from scholarscope.extraction.guards import numeric_candidates, numeric_provenance_error
from scholarscope.llm.base import StructuredRequest
from scholarscope.llm.cache import cache_key
from scholarscope.llm.fake import FakeClient
from scholarscope.pipeline import PipelineResult, run_pipeline
from scholarscope.schema import LanguageOption


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("live sockets prohibited in numeric-provenance tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def condition(kind: str, value: Any, quote: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "value": value,
        "required": True,
        "applies_to": None,
        "evidence": [{"quote": quote, "passage_id": None}],
        "notes": None,
    }


def language(overall: float, quote: str, subscore: float | None = None) -> dict[str, Any]:
    return condition(
        "language",
        {
            "logic": "any",
            "options": [
                {"test": "Example Language Test", "min_overall": overall, "min_subscore": subscore}
            ],
        },
        quote,
    )


def funding(amount: float | None = None, maximum: float | None = None) -> dict[str, Any]:
    return {
        "item": "stipend",
        "amount": amount,
        "amount_max": maximum,
        "currency": "EUR",
        "period": None,
        "note": None,
    }


def pipeline(
    *,
    conditions: list[dict[str, Any]] | None = None,
    funded: list[dict[str, Any]] | None = None,
    funding_quotes: tuple[str, ...] = (),
    linked_url: str | None = None,
    identity_link: str | None = None,
    documents: dict[str, Any] | None = None,
    deadlines: dict[str, Any] | None = None,
    extra_text: str = "",
    include_quotes: bool = True,
) -> PipelineResult:
    quotes = list(funding_quotes)
    quotes += [e["quote"] for c in conditions or [] for e in c["evidence"]]
    if documents:
        quotes += [e["quote"] for f in documents.values() for e in f["evidence"]]
    if deadlines:
        quotes += [e["quote"] for d in deadlines["deadlines"] for e in d["evidence"]]
    extra = "".join(
        f"<p>{html.escape(q)}</p>"
        for q in ([*quotes, extra_text] if include_quotes else [extra_text])
    ).encode()
    data = content("simple").replace(b"</main>", extra + b"</main>")

    def respond(req: StructuredRequest[Any]) -> str:
        answer = payload(req)
        group = req.prompt_version.split("-", 1)[0]
        if group == "conditions" and conditions is not None:
            answer = {"conditions": deepcopy(conditions)}
        if group == "funding" and funded is not None:
            answer = {"funding_coverage": field(deepcopy(funded))}
            answer["funding_coverage"]["evidence"] = [
                {"quote": q, "passage_id": None} for q in funding_quotes
            ]
            answer["funding_coverage"]["linked_url"] = linked_url
        if group == "identity" and identity_link:
            answer["application_link"] = field(identity_link)
        if group == "documents" and documents is not None:
            answer = deepcopy(documents)
        if group == "deadlines" and deadlines is not None:
            answer = deepcopy(deadlines)

        def cite(value: Any) -> None:
            if isinstance(value, dict):
                if "quote" in value:
                    value["passage_id"] = next(
                        (pid for pid, text in req.untrusted_passages if value["quote"] in text),
                        req.untrusted_passages[0][0],
                    )
                for child in value.values():
                    cite(child)
            elif isinstance(value, list):
                for child in value:
                    cite(child)

        cite(answer)
        return json.dumps(answer)

    return run_pipeline(fetch(data), FakeClient(responses=[respond] * 5))


@pytest.mark.parametrize(
    "quote,number",
    [
        ("Example grant pays 1,250 EUR.", 1250.0),
        ("Example grant pays 1,250 EUR.", 1.25),
        ("Example grant pays 1,250.50 EUR.", 1250.5),
        ("Example grant pays 1.250,50 EUR.", 1250.5),
        ("Example threshold is 3,5.", 3.5),
        ("Example grant pays 2,500.0 EUR.", 2500.0),
        ("Example allowance is €2,771.-", 2771.0),
        ("Example grant pays 1,250,000 EUR.", 1250000.0),
    ],
)
def test_numeric_token_interpretations(quote: str, number: float) -> None:
    assert number in numeric_candidates((quote,))
    assert numeric_provenance_error({"amount": number}, (quote,)) is None


def test_numeric_matching_is_exact_and_not_substring_or_word_matching() -> None:
    assert numeric_provenance_error({"value": 3.5000000001}, ("Example GPA 3.5.",))
    assert numeric_provenance_error({"value": 3.0}, ("Example threshold 13.0.",))
    assert numeric_provenance_error({"value": 35.0}, ("Example GPA 3.5.",))
    assert not numeric_candidates(("Example threshold is four-point-zero.",))


@pytest.mark.parametrize(
    "quote,domain_failure",
    [
        ("Example candidates must satisfy language proficiency.", False),
        ("Example test threshold is 0.", True),
    ],
)
def test_zero_overall_provenance_precedes_domain_validation(
    quote: str, domain_failure: bool
) -> None:
    result = pipeline(conditions=[language(0.0, quote)])
    assert result.record and result.extraction and not result.record.conditions
    rejects = result.extraction.rejected_items
    assert len(rejects) == 1 and rejects[0].index == 0
    if domain_failure:
        assert "min_overall: Input should be greater than 0" in rejects[0].reason
        assert "NUMBER_NOT_IN_QUOTE" not in rejects[0].reason
    else:
        assert rejects[0].reason == "NUMBER_NOT_IN_QUOTE:min_overall"
    assert rejects[0].raw_item["value"]["options"][0]["min_overall"] == 0.0


@pytest.mark.parametrize(
    "quote,reason",
    [
        ("Example test overall minimum is 6.", "NUMBER_NOT_IN_QUOTE:min_subscore"),
        ("Example test overall minimum is 6 and subscore 0.", "domain"),
    ],
)
def test_zero_subscore_backstop(quote: str, reason: str) -> None:
    result = pipeline(conditions=[language(6.0, quote, 0.0)])
    assert result.extraction and result.record and not result.record.conditions
    rejection = result.extraction.rejected_items[0]
    if reason == "domain":
        assert "min_subscore: Input should be greater than 0" in rejection.reason
    else:
        assert rejection.reason == reason


@pytest.mark.parametrize("name", ["min_overall", "min_subscore"])
@pytest.mark.parametrize("number", [0.0, -1.0])
def test_canonical_language_options_require_positive_scores(name: str, number: float) -> None:
    data = {"test": "Example Language Test", "min_overall": 6.0, "min_subscore": 5.0, name: number}
    with pytest.raises(ValidationError, match="greater than 0"):
        LanguageOption.model_validate(data)


@pytest.mark.parametrize("scale,reason", [(4.0, None), (5.0, "NUMBER_NOT_IN_QUOTE:scale")])
def test_gpa_value_and_scale_must_both_occur(scale: float, reason: str | None) -> None:
    claim = condition("min_gpa", {"value": 3.5, "scale": scale}, "Example GPA minimum is 3.5/4.0.")
    result = pipeline(conditions=[claim])
    assert result.extraction and result.record
    if reason:
        assert result.extraction.rejected_items[0].reason == reason
        assert not result.record.conditions
    else:
        assert not result.extraction.rejected_items
        assert result.record.conditions[0].verification == "verified"


def test_gpa_missing_value_wins_before_missing_scale() -> None:
    result = pipeline(
        conditions=[
            condition("min_gpa", {"value": 3.5, "scale": 5.0}, "Example minimum is unstated.")
        ]
    )
    assert result.extraction
    assert [r.reason for r in result.extraction.rejected_items] == ["NUMBER_NOT_IN_QUOTE:value"]


def test_language_options_use_only_their_own_condition_quotes_and_keep_siblings() -> None:
    result = pipeline(
        conditions=[
            language(7.0, "Example test overall is 6."),
            language(7.0, "Example alternative overall is 7."),
        ]
    )
    assert result.extraction and result.record
    assert [r.reason for r in result.extraction.rejected_items] == [
        "NUMBER_NOT_IN_QUOTE:min_overall"
    ]
    assert (
        len(result.record.conditions) == 1
        and result.record.conditions[0].verification == "verified"
    )


@pytest.mark.parametrize(
    "quote,rejected",
    [
        ("Example test requires overall 6 and subscore 5.", True),
        ("Example test requires overall 6 and subscore 5, or alternative overall 7.", False),
    ],
)
def test_every_language_option_is_checked(quote: str, rejected: bool) -> None:
    claim = language(6.0, quote, 5.0)
    claim["value"]["options"].append(
        {"test": "Example Alternative Test", "min_overall": 7.0, "min_subscore": None}
    )
    result = pipeline(conditions=[claim])
    assert result.record and result.extraction
    assert bool(result.extraction.rejected_items) is rejected
    if rejected:
        assert result.extraction.rejected_items[0].reason == "NUMBER_NOT_IN_QUOTE:min_overall"
        assert not result.record.conditions
    else:
        assert result.record.conditions[0].verification == "verified"


def test_missing_funding_amount_keeps_valid_siblings_and_original_raw_item() -> None:
    bad = {**funding(987.0), "fictional_extra": "retained only in raw_item"}
    result = pipeline(
        funded=[funding(500.0), bad, funding(None)],
        funding_quotes=("Example stipend is 500 EUR.",),
        extra_text="A different fictional cost is 987 EUR.",
    )
    assert result.extraction and result.record
    assert result.extraction.group_status["funding"] == "partial"
    assert not result.extraction.failed_groups
    assert [r.reason for r in result.extraction.rejected_items] == ["NUMBER_NOT_IN_QUOTE:amount"]
    rejection = result.extraction.rejected_items[0]
    assert rejection.group == "funding" and rejection.index == 1 and rejection.raw_item == bad
    kept = result.record.fields.funding_coverage.value
    assert kept and len(kept) == 2 and kept[0].amount == 500.0 and kept[1].amount is None
    assert "987" not in result.record.model_dump_json()


def test_missing_funding_maximum_and_all_rejected_group() -> None:
    result = pipeline(
        funded=[funding(500.0, 987.0)], funding_quotes=("Example stipend is 500 EUR.",)
    )
    assert result.extraction and result.record
    assert result.extraction.rejected_items[0].reason == "NUMBER_NOT_IN_QUOTE:amount_max"
    assert result.extraction.failed_groups == ("funding",)
    assert result.record.fields.funding_coverage.value is None


def test_funding_can_use_all_quotes_of_its_field() -> None:
    result = pipeline(
        funded=[funding(1250.5), funding(None, 2771.0)],
        funding_quotes=("Example stipend is 1.250,50 EUR.", "Example limit is €2,771.-"),
    )
    assert result.record and result.extraction and not result.extraction.rejected_items
    assert result.record.fields.funding_coverage.verification == "verified"


def test_numeric_then_url_then_domain_first_failure_only() -> None:
    absent_url = "https://example.invalid/not-in-the-source"
    missing_number = pipeline(funded=[funding(987.0)], linked_url=absent_url)
    assert missing_number.extraction
    assert [r.reason for r in missing_number.extraction.rejected_items] == [
        "NUMBER_NOT_IN_QUOTE:amount"
    ]
    bad_url = pipeline(
        funded=[funding(500.0)],
        funding_quotes=("Example stipend is 500 EUR.",),
        linked_url=absent_url,
    )
    assert bad_url.extraction
    assert [r.reason for r in bad_url.extraction.rejected_items] == ["URL_NOT_ON_PAGE"]
    # Missing evidence is also domain-invalid, but absent URL wins first.
    before_domain = pipeline(identity_link=absent_url)
    assert before_domain.extraction
    assert [r.reason for r in before_domain.extraction.rejected_items] == ["URL_NOT_ON_PAGE"]
    domain = pipeline(funded=[funding(None)])
    assert domain.extraction
    assert len(domain.extraction.rejected_items) == 1
    assert (
        "present requires at least one evidence quote" in domain.extraction.rejected_items[0].reason
    )


def test_word_counts_dates_times_and_age_are_outside_the_guard() -> None:
    word_quote = "Example candidates provide two references."
    documents = {
        "required_documents": field(),
        "recommenders": field({"count_min": 2, "count_max": 2, "type": None}, word_quote),
    }
    date_quote = "Example applications close in the stated season."
    deadlines = {
        "deadlines_status": "present",
        "deadlines": [deadline(date_quote, None, time="23:59", timezone="UTC")],
        "linked_url": None,
        "notes": None,
    }
    result = pipeline(
        conditions=[condition("age_min", 4, "Example minimum age is four years.")],
        documents=documents,
        deadlines=deadlines,
    )
    assert result.record and result.extraction and not result.extraction.rejected_items
    assert result.record.fields.recommenders.verification == "verified"
    assert result.record.conditions[0].verification == "verified"
    assert result.record.deadlines[0].verification == "verified"


def test_numeric_presence_does_not_replace_quote_verification() -> None:
    result = pipeline(
        conditions=[language(6.0, "Example overall threshold is 6.")], include_quotes=False
    )
    assert result.record and result.extraction and not result.extraction.rejected_items
    assert result.record.conditions[0].verification == "unverified"


@pytest.mark.parametrize(
    "group,old,new", [("identity", "v1", "v2"), ("funding", "v2", "v3"), ("conditions", "v2", "v3")]
)
def test_prompt_revisions_bump_versions_and_cache_keys(group: str, old: str, new: str) -> None:
    folder = Path(__file__).resolve().parents[1] / "scholarscope/extraction/prompts"
    old_task = (folder / f"{group}.{old}.txt").read_text(encoding="utf-8")
    new_task = (folder / f"{group}.{new}.txt").read_text(encoding="utf-8")
    assert PROMPT_VERSIONS[group] == f"{group}-{new}" and old_task != new_task
    before = request(task=old_task, prompt_version=f"{group}-{old}")
    key = cache_key("fake", "fictional", before)
    assert cache_key("fake", "fictional", replace(before, prompt_version=f"{group}-{new}")) != key
    assert cache_key("fake", "fictional", replace(before, task=new_task)) != key


def test_new_prompt_policies_are_in_the_sent_tasks() -> None:
    folder = Path(__file__).resolve().parents[1] / "scholarscope/extraction/prompts"
    identity = (folder / "identity.v2.txt").read_text(encoding="utf-8")
    funding_text = (folder / "funding.v3.txt").read_text(encoding="utf-8")
    conditions = (folder / "conditions.v3.txt").read_text(encoding="utf-8")
    assert "never an applicant prerequisite" in identity
    assert "amount is what the funder pays or grants" in funding_text
    assert "period only when the evidence quote itself states a period" in funding_text
    assert "Do not emit two conditions that restate the same quote" in conditions
    assert "Tuition-fee" in conditions and "never residency" in conditions
    assert "-> kind other with that sentence as value" in conditions
