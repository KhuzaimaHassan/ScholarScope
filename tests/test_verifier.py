"""Adversarial synthetic evidence only; no labels, snapshots, network or LLMs."""

from __future__ import annotations

import random
import re
import unicodedata
from html import escape
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from test_pdf_text import make_text_pdf
from test_schema import example

from scholarscope.cleaner import CleanedHTML, clean_html
from scholarscope.pdf_text import extract_pdf_text
from scholarscope.schema import (
    Condition,
    Evidence,
    Field,
    RequirementFields,
    RequirementRecord,
    from_gold_label,
)
from scholarscope.segmenter import SegmentedDocument, segment
from scholarscope.verifier import VERIFIER_VERSION, EvidenceResult, QuoteOutcome, verify_record


def html_doc(*paragraphs: str, max_chars: int = 1200) -> SegmentedDocument:
    return segment(
        clean_html("<main>" + "".join(f"<p>{escape(p)}</p>" for p in paragraphs) + "</main>"),
        max_chars=max_chars,
    )


def record_for(evidence: list[Evidence]) -> RequirementRecord:
    fields: dict[str, Any] = {
        name: {"status": "absent", "value": None, "evidence": []}
        for name in RequirementFields.model_fields
    }
    fields["program_name"] = {
        "status": "present",
        "value": "An unsupported value is still retained",
        "evidence": evidence,
    }
    return RequirementRecord.model_validate(
        {
            "source": {
                "url": "https://example.invalid/synthetic",
                "retrieved_on": "2026-10-23",
                "content_sha256": "0" * 64,
                "format": "html",
                "page_state": "unknown",
            },
            "fields": fields,
            "deadlines_status": "absent",
            "deadlines": [],
            "conditions": [],
        }
    )


def check_quote(
    doc: SegmentedDocument, quote: str, passage_index: int = 0
) -> tuple[Field[str], EvidenceResult]:
    record = record_for([Evidence(quote=quote, passage_id=doc.passages[passage_index].id)])
    result, report = verify_record(record, doc)
    return result.fields.program_name, report.items[0]


def oracle_normalize(text: str) -> str:
    """Independent whole-string implementation: no verifier normalization/maps."""
    text = re.sub(r"-\r?\n", "", text)
    text = "".join(c for c in text if c not in "\u00ad\u200b\u200c\u200d\u2060\ufeff")
    text = unicodedata.normalize("NFKC", text)
    for old, new in [("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")]:
        text = text.replace(old, new)
    return " ".join(text.split())


@pytest.mark.parametrize(
    "page,quote,outcome",
    [
        ("The fictional award is open.", "fictional award", "exact"),
        ("The “fictional award” is open.", 'The "fictional award"', "normalized"),
        ("The applicant’s award is open.", "applicant's award", "normalized"),
        ("Study costs – tuition — travel", "costs - tuition - travel", "normalized"),
        ("The fictional\u00a0award is open.", "fictional award", "exact"),
        ("The fictional schol\u00adarship is open.", "fictional scholarship", "normalized"),
        (
            "The fictional a\u200bw\u200ca\u200dr\u2060d\ufeff is open.",
            "fictional award",
            "normalized",
        ),
        ("The oﬃce award is open.", "office award", "normalized"),
        ("The cafe\u0301 award is open.", "café award", "normalized"),
        ("The A\u0315\u0300 award is open.", "À\u0315 award", "normalized"),
        ("The \u1100\u1161\u11a8 award is open.", "각 award", "normalized"),
        ("The ＡＷＡＲＤ ２０２７ is open.", "AWARD 2027", "normalized"),
    ],
)
def test_formatting_only_matches_with_original_offsets(page: str, quote: str, outcome: str) -> None:
    doc = html_doc(page)
    field, item = check_quote(doc, quote)
    assert field.verification == "verified" and field.usable_for_logic
    assert item.outcome == outcome and item.matched is not None
    start, end = item.matched
    assert oracle_normalize(doc.text[start:end]) == oracle_normalize(quote)
    assert item.passage_ids == (doc.passages[0].id,)


@pytest.mark.parametrize(
    "quote,outcome",
    [
        ("GPA 3.6", "not_found"),
        ("cycle 2026", "not_found"),
        ("Applicants must send records", "not_found"),
        ("Applicants submit records", "not_found"),
        ("records submit must Applicants", "not_found"),
        ("applicants must submit records", "not_found"),
        ("Applicаnts must submit records", "not_found"),  # Cyrillic a.
        ("Applicants ... records", "invalid_quote"),
        ("Applicants … records", "invalid_quote"),
        ("Applicants [...] records", "invalid_quote"),
        ("A B", "invalid_quote"),
        ("1234567", "invalid_quote"),
        ("..........", "invalid_quote"),
        ("Invented supporting evidence", "not_found"),
    ],
)
def test_adversarial_changes_never_verify(quote: str, outcome: str) -> None:
    doc = html_doc("Applicants must submit records. GPA 3.5 for cycle 2027.")
    field, item = check_quote(doc, quote)
    assert field.verification == "unverified" and not field.usable_for_logic
    assert item.outcome == outcome and item.matched is None
    assert field.evidence[0].quote == quote and field.value is not None
    assert item.near_match is None  # Deliberately no edit-distance matching.


def test_normalization_is_symmetric_including_quote_whitespace() -> None:
    doc = html_doc('The "fictional award" - tuition is covered.')
    field, item = check_quote(doc, "  The\u00a0“fictional award”\t— tuition  ")
    assert field.verification == "verified" and item.outcome == "normalized"
    assert item.matched is not None
    assert oracle_normalize(doc.text[slice(*item.matched)]) == oracle_normalize(item.quote)


def test_pdf_line_break_hyphenation_and_cross_page_offsets() -> None:
    doc = segment(
        extract_pdf_text(
            make_text_pdf(
                [
                    ["Fictional docu-", "ment requirements remain available."],
                    ["Additional fictional supporting records must be submitted."],
                ]
            )
        )
    )
    field, item = check_quote(doc, "Fictional document requirements remain available.")
    assert field.verification == "verified" and item.outcome == "normalized"
    assert item.matched is not None and "docu-\nment" in doc.text[slice(*item.matched)]
    quote = "available.\n\nAdditional fictional"
    field, item = check_quote(doc, quote)
    assert field.verification == "verified" and item.outcome == "spans_passages"
    assert item.passage_ids == tuple(p.id for p in doc.passages)


def test_hyphen_followed_by_space_then_newline_is_not_joined() -> None:
    # cleaner preserves pre line breaks but normalizes trailing spaces, so use
    # generated PDF output's explicit whitespace-preserving document container.
    doc = segment(CleanedHTML(text="The fictional docu- \nment requirements.", offset_map=()))
    field, item = check_quote(doc, "fictional document requirements")
    assert field.verification == "unverified" and item.outcome == "not_found"


def test_partial_compatibility_expansion_cannot_certify_a_different_source_slice() -> None:
    doc = html_doc("The ﬁ award is fictional.")
    field, item = check_quote(doc, "i award")
    assert field.verification == "unverified" and item.matched is None


def test_other_passage_suggestion_does_not_repair_citation() -> None:
    doc = html_doc(
        "The first fictional award is open.", "A different second award is closed.", max_chars=50
    )
    field, item = check_quote(doc, "second award is closed")
    assert field.verification == "unverified"
    assert item.outcome == "found_in_other_passage"
    assert item.suggested_passage_ids == (doc.passages[1].id,)
    assert field.evidence[0].passage_id == doc.passages[0].id


@pytest.mark.parametrize("passage_id", [None, "unknown-id"])
def test_missing_citation_reports_unique_suggestion_only(passage_id: str | None) -> None:
    doc = html_doc("The fictional award is open.")
    record = record_for([Evidence(quote="fictional award", passage_id=passage_id)])
    field, report = verify_record(record, doc)
    assert field.fields.program_name.verification == "unverified"
    assert report.items[0].outcome == "no_passage_cited"
    assert report.items[0].suggested_passage_ids == (doc.passages[0].id,)


def test_invalid_quote_precedes_missing_citation_and_nonunique_suggestions_are_withheld() -> None:
    doc = html_doc("Repeated award text. Repeated award text.")
    record = record_for([Evidence(quote="A B"), Evidence(quote="Repeated award text")])
    _, report = verify_record(record, doc)
    assert report.items[0].outcome == "invalid_quote"
    assert report.items[1].outcome == "no_passage_cited"
    assert report.items[1].occurrences == 2
    assert report.items[1].suggested_passage_ids == ()


@pytest.mark.parametrize("citation_index", [0, 1])
def test_sentence_spanning_segment_boundary_is_verified(citation_index: int) -> None:
    doc = html_doc(
        "All fictional applicants must submit their complete supporting records promptly.",
        max_chars=50,
    )
    quote = doc.text[doc.passages[0].end - 20 : doc.passages[1].start + 20]
    field, item = check_quote(doc, quote, citation_index)
    assert field.verification == "verified" and item.outcome == "spans_passages"
    assert item.passage_ids == tuple(p.id for p in doc.passages)
    assert item.matched is not None and doc.text[slice(*item.matched)] == quote


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"context_before": "South route."},
        {"context_after": "Final route."},
        {"context_before": "not on this page"},
    ],
)
def test_duplicate_locations_and_context(context: dict[str, str]) -> None:
    doc = html_doc(
        "North route. Repeated award text. South route. Repeated award text. Final route."
    )
    evidence = Evidence(quote="Repeated award text.", passage_id=doc.passages[0].id, **context)
    record, report = verify_record(record_for([evidence]), doc)
    item = report.items[0]
    disambiguates = bool(context) and "not on this page" not in context.values()
    assert record.fields.program_name.verification == "verified"
    assert item.occurrences == 2 and item.ambiguous_location is not disambiguates
    expected = doc.text.rindex(evidence.quote) if disambiguates else doc.text.index(evidence.quote)
    assert item.matched == (expected, expected + len(evidence.quote))


def test_every_quote_must_pass_and_inputs_are_not_mutated() -> None:
    doc = html_doc("The amount is EUR 800. The period is monthly.")
    record = record_for(
        [
            Evidence(quote="amount is EUR 800", passage_id=doc.passages[0].id),
            Evidence(quote="period is annually", passage_id=doc.passages[0].id),
        ]
    )
    record.fields.program_name.verification = "verified"
    record.fields.program_name.confidence = 0.999
    before = record.model_dump_json()
    result, report = verify_record(record, doc)
    assert result is not record and result.fields.program_name is not record.fields.program_name
    assert record.model_dump_json() == before
    assert [r.outcome for r in report.items] == ["exact", "not_found"]
    assert result.fields.program_name.verification == "unverified"
    assert result.fields.program_name.value == record.fields.program_name.value
    assert result.fields.program_name.evidence == record.fields.program_name.evidence
    assert result.fields.program_name.confidence == 0.999
    assert verify_record(record, doc) == (result, report)
    assert report.verifier_version == VERIFIER_VERSION == "1"
    assert report.totals[QuoteOutcome.EXACT] == 1
    assert report.totals[QuoteOutcome.NOT_FOUND] == 1
    assert sum(report.totals.values()) == 2


def add_claims(record: RequirementRecord, evidence: list[Evidence]) -> RequirementRecord:
    data = record.model_dump()
    data["deadlines_status"] = "present"
    data["deadlines"] = [
        {
            "label": "Fictional deadline",
            "type": "application",
            "cycle_year": 2027,
            "date": "2027-05-01",
            "time": None,
            "timezone": None,
            "rolling": False,
            "status": "present",
            "evidence": evidence,
            "verification": "verified",
        }
    ]
    data["conditions"] = [
        {
            "kind": "min_gpa",
            "value": {"value": 3.5, "scale": 4.0},
            "required": True,
            "applies_to": None,
            "evidence": evidence,
            "verification": "verified",
        }
    ]
    return RequirementRecord.model_validate(data)


def test_deadlines_conditions_and_nonclaim_fields() -> None:
    doc = html_doc("The fictional evidence is present.")
    evidence = [Evidence(quote="Completely fabricated quote", passage_id=doc.passages[0].id)]
    record = add_claims(record_for(evidence), evidence)
    data = record.model_dump()
    data["fields"]["institution"] = {
        "status": "in_linked_document",
        "value": None,
        "evidence": [],
        "linked_url": "https://example.invalid/linked",
    }
    record = RequirementRecord.model_validate(data)
    original = record.model_dump_json()
    result, report = verify_record(record, doc)
    assert record.model_dump_json() == original
    assert result.deadlines[0].verification == "unverified"
    assert result.conditions[0].verification == "unverified"
    assert not result.deadlines[0].usable_for_logic and not result.conditions[0].usable_for_logic
    assert result.deadlines[0].date == "2027-05-01"
    assert result.conditions[0].value == record.conditions[0].value
    assert {r.owner_path for r in report.items} == {
        "fields.program_name",
        "deadlines[0]",
        "conditions[0]",
    }
    assert result.fields.institution.verification == "not_checked"
    assert result.fields.application_link.verification == "not_checked"


def test_condition_state_validation_and_gold_conversion_reset() -> None:
    data = example()
    for condition in data["conditions"]:
        condition["verification"] = "verified"
    result = from_gold_label(data)
    assert all(
        c.verification == "not_checked" and not c.usable_for_logic for c in result.conditions
    )
    for verification in ["verified", "unverified"]:
        condition = {**data["conditions"][0], "verification": verification, "evidence": []}
        with pytest.raises(ValidationError):
            TypeAdapter(Condition).validate_python(condition)
    with pytest.raises(ValidationError):
        TypeAdapter(Condition).validate_python({**data["conditions"][0], "verification": "present"})


def test_ambiguous_claim_can_verify_presence_but_is_not_usable() -> None:
    doc = html_doc("The award has conflicting fictional names.")
    record = record_for(
        [Evidence(quote="conflicting fictional names", passage_id=doc.passages[0].id)]
    )
    data = record.model_dump()
    data["fields"]["program_name"].update(status="ambiguous", value=None)
    result, _ = verify_record(RequirementRecord.model_validate(data), doc)
    assert result.fields.program_name.verification == "verified"
    assert not result.fields.program_name.usable_for_logic


def test_all_seven_fields_are_checked_without_judging_value_support() -> None:
    doc = html_doc("This quote says nothing about the supplied values.")
    data = record_for([Evidence(quote="Unused initial quote")]).model_dump()
    values: dict[str, Any] = {
        "program_name": "Unrelated award",
        "institution": "Invented institution",
        "degree_levels": ["master"],
        "funding_coverage": [{"item": "tuition"}],
        "required_documents": ["transcript"],
        "recommenders": {"count_min": 2},
        "application_link": "https://example.invalid/apply",
    }
    for name, value in values.items():
        data["fields"][name] = {
            "status": "present",
            "value": value,
            "evidence": [
                {"quote": "nothing about the supplied values", "passage_id": doc.passages[0].id}
            ],
            "verification": "unverified",
        }
    record = RequirementRecord.model_validate(data)
    result, report = verify_record(record, doc)
    for name in RequirementFields.model_fields:
        field = getattr(result.fields, name)
        assert field.verification == ("verified" if field.evidence else "not_checked")
    assert len(report.items) == 7
    assert all(r.outcome == "exact" for r in report.items)


def test_exact_and_normalized_ranges_of_one_location_are_not_double_counted() -> None:
    doc = html_doc("Before the fictional award after.")
    field, item = check_quote(doc, " fictional award ")
    assert field.verification == "verified" and item.outcome == "exact"
    assert item.occurrences == 1 and not item.ambiguous_location
    assert item.matched is not None and doc.text[slice(*item.matched)] == item.quote


def test_normalized_in_cited_passage_precedes_exact_in_another() -> None:
    doc = html_doc(
        "The fictional “award name” is open.", 'The fictional "award name" is closed.', max_chars=50
    )
    field, item = check_quote(doc, 'fictional "award name"')
    assert field.verification == "verified" and item.outcome == "normalized"
    assert item.passage_ids == (doc.passages[0].id,)


def test_exact_outcome_precedes_normalized_even_when_context_points_to_variant() -> None:
    doc = html_doc('First "award name". Second “award name”.')
    evidence = Evidence(
        quote='"award name"', passage_id=doc.passages[0].id, context_before="Second"
    )
    _, report = verify_record(record_for([evidence]), doc)
    item = report.items[0]
    assert item.outcome == "exact" and item.occurrences == 1
    assert item.matched is not None and doc.text[slice(*item.matched)] == evidence.quote


def test_match_across_three_passages_reports_every_touched_id() -> None:
    doc = html_doc(
        "Fictional applicant records must be submitted with sufficient supporting "
        "materials and complete transcripts before the published application window ends.",
        max_chars=50,
    )
    assert len(doc.passages) >= 3
    quote = doc.text[doc.passages[0].end - 12 : doc.passages[2].start + 12]
    field, item = check_quote(doc, quote)
    assert field.verification == "verified" and item.outcome == "spans_passages"
    assert item.passage_ids == tuple(p.id for p in doc.passages[:3])


@pytest.mark.parametrize(
    "raw,quote",
    [
        ("The fictional\u00a0\u00a0award is open.", "fictional award"),
        ("The fictional\t\n award is open.", "fictional award"),
        ("The fictional docu-\r\nment is needed.", "fictional document"),
    ],
)
def test_raw_formatting_ranges_round_trip(raw: str, quote: str) -> None:
    # Direct synthetic container additionally exercises whitespace the cleaner
    # would already collapse; normal verifier callers also include PDF output.
    doc = segment(CleanedHTML(text=raw, offset_map=()))
    field, item = check_quote(doc, quote)
    assert field.verification == "verified" and item.matched is not None
    assert oracle_normalize(raw[slice(*item.matched)]) == oracle_normalize(quote)


def test_empty_document_does_not_trust_existing_verified_state() -> None:
    record = record_for([Evidence(quote="Invented evidence quote", passage_id="unknown")])
    record.fields.program_name.verification = "verified"
    result, report = verify_record(record, html_doc(""))
    assert result.fields.program_name.verification == "unverified"
    assert report.items[0].outcome == "no_passage_cited"


def test_independent_oracle_presence_and_original_offsets_on_200_seeded_records() -> None:
    rng = random.Random(20)
    verified = 0
    for _ in range(200):
        paragraphs = [
            f"The {rng.choice(['fictional', 'café', 'oﬃce', 'À'])} award {i} — "
            f"amount {rng.randint(100, 999)} for cycle 2027."
            for i in range(rng.randint(2, 5))
        ]
        doc = html_doc(*paragraphs, max_chars=rng.choice([50, 80, 1200]))
        passage = rng.choice(doc.passages)
        quote = oracle_normalize(passage.text)
        change = rng.randrange(5)
        if change == 1:
            quote = quote.replace("2027", "2026")
        elif change == 2:
            quote = quote.replace("award", "reward")
        elif change == 3:
            quote = quote.replace("amount", "AMOUNT")
        evidence = [Evidence(quote=quote, passage_id=passage.id if change != 4 else "unknown")]
        record = add_claims(record_for(evidence), evidence)
        result, report = verify_record(record, doc)
        states = {
            "fields.program_name": result.fields.program_name.verification,
            "deadlines[0]": result.deadlines[0].verification,
            "conditions[0]": result.conditions[0].verification,
        }
        for item in report.items:
            if states[item.owner_path] != "verified":
                continue
            verified += 1
            assert item.matched is not None
            start, end = item.matched
            assert oracle_normalize(doc.text[start:end]) == oracle_normalize(item.quote)
            # Independent oracle over the cited contiguous passage window.
            touched = [p for p in doc.passages if start < p.end and p.start < end]
            window = doc.text[touched[0].start : touched[-1].end]
            assert oracle_normalize(item.quote) in oracle_normalize(window)
            assert passage.start <= start < passage.end or passage.start < end <= passage.end
            assert item.passage_ids == tuple(p.id for p in touched)
        assert verify_record(record, doc) == (result, report)
    assert verified > 100  # Not a vacuous implication with every claim rejected.
