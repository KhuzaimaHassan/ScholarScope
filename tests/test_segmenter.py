"""Synthetic HTML and in-memory generated PDFs only; never private evaluation data."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import FrozenInstanceError, replace
from html import escape

import pytest
from bs4 import BeautifulSoup
from test_pdf_text import make_text_pdf

from scholarscope.cleaner import CleanedHTML, SourceSpan, clean_html
from scholarscope.pdf_text import ExtractedPDF, PDFTextSpan, extract_pdf_text
from scholarscope.segmenter import (
    SEGMENTER_VERSION,
    SegmentedDocument,
    locate,
    passage_by_id,
    segment,
)


def check_document(doc: SegmentedDocument, original: str, max_chars: int) -> None:
    assert doc.text == original
    assert doc.segmenter_version == SEGMENTER_VERSION == "1"
    covered = [0] * len(original)
    previous_end = 0
    ids = []
    for index, passage in enumerate(doc.passages):
        assert passage.index == index
        assert previous_end <= passage.start < passage.end <= len(original)
        assert not original[previous_end : passage.start].strip()
        assert passage.text == original[passage.start : passage.end]
        assert passage._document_text is doc.text
        assert passage.exceeds_max == (len(passage.text) > max_chars)
        assert len(passage.text) <= 2 * max_chars or not any(c.isspace() for c in passage.text)
        digest = hashlib.sha256(" ".join(passage.text.split()).encode()).hexdigest()[:8]
        assert passage.text_hash == digest
        assert passage.id == f"p{index:04d}-{digest}"
        assert passage_by_id(doc, passage.id) is passage
        assert locate(doc, passage.id, passage.text) == (passage.start, passage.end)
        for char in range(passage.start, passage.end):
            covered[char] += 1
        for ref in passage.source_refs:
            assert passage.start <= ref.start < ref.end <= passage.end
        ids.append(passage.id)
        previous_end = passage.end
    assert not original[previous_end:].strip()
    assert len(ids) == len(set(ids))
    assert all(count == 1 for c, count in zip(original, covered, strict=True) if not c.isspace())


def html_lines(lines: list[str]) -> CleanedHTML:
    return clean_html("<main><pre>" + escape("\n".join(lines)) + "</pre></main>")


def test_round_trip_exact_quotes_and_immutable_shared_text() -> None:
    source = clean_html(
        "<main><h1>Fictional award</h1><p>One &amp; two <b>bold words</b>.</p>"
        "<p>Another sentence for the synthetic example.</p></main>"
    )
    doc = segment(source, max_chars=50)
    assert doc.source_kind == "html" and doc.unsupported_reason is None
    check_document(doc, source.text, 50)
    for passage in doc.passages:
        for quote in passage.text.splitlines():
            found = locate(doc, passage.id, quote)
            assert found is not None
            assert doc.text[found[0] : found[1]] == quote
    with pytest.raises(FrozenInstanceError):
        doc.passages[0].start = 3  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        doc.text = "Changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="share"):
        replace(doc, text=doc.text + " changed")
    assert passage_by_id(doc, "missing") is None
    assert locate(doc, "missing", "One") is None
    assert locate(doc, doc.passages[0].id, "") is None
    assert locate(doc, doc.passages[0].id, "one") is None
    assert locate(doc, doc.passages[0].id, "One & two bold wordz") is None


def test_html_refs_round_trip_including_collapsed_whitespace() -> None:
    markup = "<main><h2>Heading</h2><p>alpha    beta <b>gamma</b> delta.</p>" + (
        "<p>" + "Fictional supporting words. " * 9 + "</p></main>"
    )
    source = clean_html(markup)
    doc = segment(source, max_chars=50)
    soup = BeautifulSoup(markup, "lxml")
    # Resolve text node paths independently through lxml, as in the cleaner tests.
    from lxml import html as lxml_html

    tree = lxml_html.document_fromstring(str(soup)).getroottree()
    for passage in doc.passages:
        first_ref = passage.source_refs[0]
        assert isinstance(first_ref, SourceSpan)
        assert passage.locator == first_ref.node_path
        for ref in passage.source_refs:
            assert isinstance(ref, SourceSpan)
            if not ref.is_separator:
                assert ref.source_start is not None and ref.source_end is not None
                raw = str(tree.xpath(ref.node_path)[0])[ref.source_start : ref.source_end]
                assert re.sub(r"\s+", " ", raw) == doc.text[ref.start : ref.end]
    check_document(doc, source.text, 50)


def test_determinism_uniqueness_and_repeated_lines() -> None:
    source = html_lines(["Repeated fictional line " + "x" * 20] * 5)
    doc = segment(source, max_chars=50)
    assert segment(source, max_chars=50) == doc
    assert len(doc.passages) == 5
    assert len({p.text_hash for p in doc.passages}) == 1
    assert len({p.id for p in doc.passages}) == 5
    check_document(doc, source.text, 50)


def test_appending_paragraph_only_changes_last_passage() -> None:
    markup = "<main>" + "".join(
        f"<p>Fictional paragraph {i} has some details.</p>" for i in range(7)
    )
    before = segment(clean_html(markup + "</main>"), max_chars=80)
    after = segment(
        clean_html(markup + "<p>An appended fictional paragraph.</p></main>"), max_chars=80
    )
    assert len(before.passages) > 1
    assert [p.id for p in before.passages[:-1]] == [
        p.id for p in after.passages[: len(before.passages) - 1]
    ]
    assert before.passages[-1].id != after.passages[-1].id


def test_headings_start_passages_and_travel_with_content() -> None:
    source = clean_html(
        "<main><p>Before heading.</p><h1>First heading</h1><p>First body.</p>"
        "<h2>Second heading</h2><p>Second body.</p></main>"
    )
    doc = segment(source, max_chars=100)
    assert [p.text for p in doc.passages] == [
        "Before heading.",
        "First heading\nFirst body.",
        "Second heading\nSecond body.",
    ]
    assert [p.section_heading for p in doc.passages] == [None, "First heading", "Second heading"]
    check_document(doc, source.text, 100)


def test_consecutive_headings_with_content_are_one_block() -> None:
    source = clean_html("<main><h1>Overview</h1><h2>Details</h2><p>" + "b" * 40 + "</p></main>")
    doc = segment(source, max_chars=50)
    assert len(doc.passages) == 1
    assert doc.passages[0].section_heading == "Details"
    assert doc.passages[0].exceeds_max
    check_document(doc, source.text, 50)


@pytest.mark.parametrize("body_length, expected_count", [(79, 1), (80, 2)])
def test_heading_block_at_and_over_hard_max(body_length: int, expected_count: int) -> None:
    source = clean_html("<main><h1>" + "H" * 20 + "</h1><p>" + "b" * body_length + "</p></main>")
    doc = segment(source, max_chars=50)
    check_document(doc, source.text, 50)
    assert len(doc.passages) == expected_count
    if body_length == 79:
        assert len(doc.passages[0].text) == 100
        assert doc.passages[0].exceeds_max


def test_heading_overflow_can_leave_a_heading_alone() -> None:
    source = clean_html("<main><h1>" + "H" * 30 + "</h1><p>" + "word " * 19 + "end</p></main>")
    doc = segment(source, max_chars=50)
    assert doc.passages[0].text == "H" * 30
    assert len(doc.passages) > 1
    check_document(doc, source.text, 50)


def test_many_headings_break_only_on_heading_boundaries_when_overflowing() -> None:
    source = clean_html(
        "<main>"
        + "".join(f"<h2>{str(i) * 30}</h2>" for i in range(5))
        + "<p>Following body.</p></main>"
    )
    doc = segment(source, max_chars=50)
    assert all(p.text.splitlines()[0] in source.text.splitlines() for p in doc.passages)
    assert doc.passages[-1].text.endswith("Following body.")
    check_document(doc, source.text, 50)


def test_final_heading_can_be_alone() -> None:
    doc = segment(clean_html("<main><p>Body.</p><h2>Last heading</h2></main>"), max_chars=50)
    assert doc.passages[-1].text == "Last heading"


@pytest.mark.parametrize("cell_lengths, expected_count", [([35, 35], 1), ([60, 60, 60], 3)])
def test_table_row_stays_whole_below_hard_max_else_splits_at_cells(
    cell_lengths: list[int],
    expected_count: int,
) -> None:
    cells = [chr(65 + i) * n for i, n in enumerate(cell_lengths)]
    source = clean_html(
        "<main><table><tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr></table></main>"
    )
    doc = segment(source, max_chars=50)
    assert len(doc.passages) == expected_count
    assert all(any(cell in p.text for p in doc.passages) for cell in cells)
    assert any(p.exceeds_max for p in doc.passages)
    check_document(doc, source.text, 50)


def test_literal_pipe_in_a_cell_is_not_a_generated_cell_delimiter() -> None:
    first = "first cell with | literal separator " + "x" * 40
    second = "y" * 60
    source = clean_html(f"<table><tr><td>{first}</td><td>{second}</td></tr></table>")
    doc = segment(source, max_chars=50)
    assert any(first in p.text for p in doc.passages)
    check_document(doc, source.text, 50)


def test_cell_above_hard_max_uses_ordinary_splitting() -> None:
    source = clean_html(
        "<table><tr><td>" + "ordinary words " * 15 + "</td><td>Other</td></tr></table>"
    )
    doc = segment(source, max_chars=50)
    assert len(doc.passages) > 2
    check_document(doc, source.text, 50)


@pytest.mark.parametrize(
    "markup",
    [
        "<main><h1>" + "long heading words " * 12 + "</h1></main>",
        "<main><p>" + "word " * 30 + "</p></main>",
        "<main><p>"
        + "One sentence. Another sentence? Third sentence! Last sentence; " * 4
        + "</p></main>",
    ],
)
def test_long_heading_and_ordinary_lines_split_without_rewriting(markup: str) -> None:
    source = clean_html(markup)
    doc = segment(source, max_chars=50)
    assert len(doc.passages) > 1
    assert all(len(p.text) <= 50 for p in doc.passages)
    check_document(doc, source.text, 50)


def test_sentence_ends_preferred_to_later_whitespace() -> None:
    source = html_lines(["A brief sentence. " + "following " * 9])
    doc = segment(source, max_chars=50)
    assert doc.passages[0].text == "A brief sentence."
    check_document(doc, source.text, 50)


@pytest.mark.parametrize("container", ["p", "h1", "td"])
def test_unbreakable_word_is_only_hard_max_exception(container: str) -> None:
    word = "w" * 151
    markup = f"<{container}>{word}</{container}>"
    if container == "td":
        markup = "<table><tr>" + markup + "<td>Other cell</td></tr></table>"
    source = clean_html(markup)
    doc = segment(source, max_chars=50)
    assert any(p.text == word and p.exceeds_max for p in doc.passages)
    check_document(doc, source.text, 50)


def test_pdf_page_boundaries_and_per_page_offset_round_trip() -> None:
    source = extract_pdf_text(
        make_text_pdf(
            [
                ["First fictional page has a sufficiently long sentence.", "Another line."],
                ["Second fictional page has different supporting content.", "Last line."],
            ]
        )
    )
    assert source.status == "ok"
    doc = segment(source, max_chars=1200)
    assert doc.source_kind == "pdf"
    assert [p.locator for p in doc.passages] == ["p.1", "p.2"]
    assert all(p.section_heading is None for p in doc.passages)
    for passage in doc.passages:
        for ref in passage.source_refs:
            assert isinstance(ref, PDFTextSpan)
            if not ref.is_separator:
                page = source.pages[ref.page_number - 1]
                assert doc.text[ref.start : ref.end] == page.text[ref.page_start : ref.page_end]
    assert segment(source) == doc
    check_document(doc, source.text, 1200)


def test_pdf_long_lines_clip_page_ranges() -> None:
    source = extract_pdf_text(make_text_pdf([["Fictional page words " * 8]]))
    doc = segment(source, max_chars=50)
    assert len(doc.passages) > 1
    assert all(p.locator == "p.1" for p in doc.passages)
    for passage in doc.passages:
        ref = passage.source_refs[0]
        assert isinstance(ref, PDFTextSpan)
        assert source.pages[0].text[ref.page_start : ref.page_end] == passage.text
    check_document(doc, source.text, 50)


@pytest.mark.parametrize(
    "source",
    [
        clean_html(""),
        clean_html("   "),
        extract_pdf_text(b"not a PDF"),
        extract_pdf_text(make_text_pdf([[]])),
        ExtractedPDF(status="encrypted_unsupported"),
        ExtractedPDF(status="ok"),
    ],
)
def test_empty_or_unsupported_sources_have_reason(source: CleanedHTML | ExtractedPDF) -> None:
    doc = segment(source)
    assert doc.text == source.text and doc.passages == () and doc.unsupported_reason


@pytest.mark.parametrize("max_chars", [-1, 0, 49])
def test_invalid_max_chars(max_chars: int) -> None:
    with pytest.raises(ValueError, match="at least 50"):
        segment(clean_html(""), max_chars=max_chars)


def test_non_ascii_and_combining_characters_survive() -> None:
    source = html_lines(["申请条件 — العربية — e\u0301cole " * 7, "日本語の文章。 " * 8])
    doc = segment(source, max_chars=50)
    check_document(doc, source.text, 50)
    assert "e\u0301cole" in doc.text
    assert all(not p.text.startswith("\u0301") for p in doc.passages)


def test_seeded_random_line_sets_coverage_round_trip_and_determinism() -> None:
    # Hypothesis is not installed locally: no dependency/network fetch, fixed seed.
    rng = random.Random(13)
    words = ["fictional", "word", "e\u0301cole", "申请", "العربية", "z" * 130, "end.", "item;"]
    for _ in range(100):
        lines = [
            " ".join(rng.choice(words) for _ in range(rng.randint(0, 14)))
            for _ in range(rng.randint(0, 12))
        ]
        source = html_lines(lines)
        limit = rng.choice([50, 60, 100, 1200])
        doc = segment(source, max_chars=limit)
        check_document(doc, source.text, limit)
        assert segment(source, max_chars=limit) == doc
