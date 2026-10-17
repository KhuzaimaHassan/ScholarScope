from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from scholarscope.pdf_text import ExtractedPDF, extract_pdf_text, locator


# All PDF bytes and images are generated here in memory, never downloaded or saved.
def make_text_pdf(pages: Sequence[Sequence[str]]) -> bytes:
    output = BytesIO()
    canvas = Canvas(output, pagesize=(612, 792), invariant=1)
    for lines in pages:
        canvas.setFont("Helvetica", 10)
        for row, line in enumerate(lines):
            canvas.drawString(72, 720 - row * 18, line)
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def assert_offset_round_trip(result: ExtractedPDF) -> None:
    cursor = 0
    for span in result.offset_map:
        assert span.start == cursor
        assert span.start < span.end <= len(result.text)
        assert 1 <= span.page_number <= result.page_count
        page = result.pages[span.page_number - 1]
        assert page.page_number == span.page_number
        assert 0 <= span.page_start <= span.page_end <= len(page.text)
        if span.is_separator:
            assert result.text[span.start : span.end] == "\n\n"
            assert span.page_start == span.page_end == len(page.text)
        else:
            assert result.text[span.start : span.end] == page.text[span.page_start : span.page_end]
        assert result.locator(span.start) == f"p.{span.page_number}"
        cursor = span.end
    assert cursor == len(result.text)


def test_multi_page_text_offsets_and_locators() -> None:
    lines = [
        ["Fictional Research Award", "The award covers tuition and a monthly living allowance."],
        ["Eligibility requirements", "Applicants must hold a recognised undergraduate degree."],
        [
            "Deadlines and evidence",
            "The application deadline is 1 May 2027 for this fictional call.",
        ],
    ]
    data = make_text_pdf(lines)
    result = extract_pdf_text(data)
    assert result.status == "ok"
    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert [page.text for page in result.pages] == ["\n".join(page) for page in lines]
    assert result.text == "\n\n".join(page.text for page in result.pages)
    assert extract_pdf_text(data) == result
    assert_offset_round_trip(result)

    start = result.text.index("application deadline")
    span = next(span for span in result.offset_map if span.start <= start < span.end)
    page_start = span.page_start + start - span.start
    quote = "application deadline is 1 May 2027"
    assert result.pages[2].text[page_start : page_start + len(quote)] == quote
    assert result.text[start : start + len(quote)] == quote
    assert locator(result, start) == result.locator(start) == "p.3"
    assert result.locator(len(result.text) - 1) == "p.3"


def test_image_only_pdf_is_scanned_unsupported() -> None:
    output = BytesIO()
    canvas = Canvas(output, pagesize=(612, 792), invariant=1)
    image = Image.new("RGB", (16, 16), color=(64, 128, 192))
    canvas.drawImage(ImageReader(image), 72, 500, width=128, height=128)
    canvas.showPage()
    canvas.save()
    data = output.getvalue()
    assert len(PdfReader(BytesIO(data)).pages[0].images) == 1
    result = extract_pdf_text(data)
    assert result.status == "scanned_unsupported"
    assert result.page_count == 1
    assert result.text == ""
    assert [page.text for page in result.pages] == [""]
    assert result.offset_map == ()
    assert result.locator(0) is None
    assert extract_pdf_text(data) == result


@pytest.mark.parametrize("user_password", ["fictional-password", ""])
def test_encryption_requires_password_only_when_empty_password_fails(user_password: str) -> None:
    data = make_text_pdf([["Eligibility: applicants must have a recognised university degree."]])
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(data)))
    writer.encrypt(user_password=user_password, owner_password="fictional-owner-password")
    output = BytesIO()
    writer.write(output)
    result = extract_pdf_text(output.getvalue())
    assert extract_pdf_text(output.getvalue()) == result
    if user_password:
        assert result.status == "encrypted_unsupported"
        assert result.text == ""
        assert result.pages == ()
        assert result.offset_map == ()
        assert result.page_count == 0  # Unavailable without opening the page tree.
        assert result.locator(0) is None
    else:
        assert result.status == "ok"
        assert result.page_count == 1
        assert "recognised university degree" in result.text
        assert_offset_round_trip(result)


@pytest.mark.parametrize("data", [b"garbage bytes", b"", b"%PDF-1.4\nbroken\n%%EOF"])
def test_corrupt_bytes_return_invalid_without_raising(data: bytes) -> None:
    result = extract_pdf_text(data)
    assert result == ExtractedPDF(status="invalid")
    assert extract_pdf_text(data) == result
    assert locator(result, 0) is None


def test_malformed_page_content_returns_invalid_without_partial_text() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Contents")] = NumberObject(42)
    output = BytesIO()
    writer.write(output)
    result = extract_pdf_text(output.getvalue())
    assert result.status == "invalid"
    assert result.text == ""
    assert result.pages == ()
    assert result.offset_map == ()
    assert result.page_count == 1


def test_zero_page_pdf_is_low_text_unsupported() -> None:
    output = BytesIO()
    PdfWriter().write(output)
    result = extract_pdf_text(output.getvalue())
    assert result.status == "scanned_unsupported"
    assert result.page_count == 0
    assert result.text == ""
    assert result.pages == ()
    assert result.offset_map == ()


def test_blank_page_pdf_is_low_text_unsupported() -> None:
    result = extract_pdf_text(make_text_pdf([[]]))
    assert result.status == "scanned_unsupported"
    assert result.page_count == 1
    assert result.text == ""
    assert [page.text for page in result.pages] == [""]
    assert result.offset_map == ()


@pytest.mark.parametrize(
    ("characters", "page_count", "expected"),
    [(24, 1, "scanned_unsupported"), (25, 1, "ok"), (49, 2, "scanned_unsupported"), (50, 2, "ok")],
)
def test_low_text_threshold_is_relative_to_page_count(
    characters: int, page_count: int, expected: str
) -> None:
    lines = [["A" * characters]] + [[] for _ in range(page_count - 1)]
    result = extract_pdf_text(make_text_pdf(lines))
    assert result.status == expected
    assert result.page_count == page_count
    assert len(result.pages) == page_count
    if expected == "scanned_unsupported":
        assert result.text == ""
        assert all(page.text == "" for page in result.pages)
        assert result.offset_map == ()


def test_blank_middle_page_keeps_physical_page_numbers() -> None:
    data = make_text_pdf(
        [
            ["Funding covers the full tuition cost and a regular monthly stipend."],
            [],
            ["Applicants must submit transcripts and two academic references."],
        ]
    )
    result = extract_pdf_text(data)
    assert result.status == "ok"
    assert result.page_count == 3
    assert result.pages[1].page_number == 2
    assert result.pages[1].text == ""
    assert result.locator(result.text.index("Applicants")) == "p.3"
    assert_offset_round_trip(result)


def test_hyphenation_wording_and_language_are_not_rewritten() -> None:
    result = extract_pdf_text(
        make_text_pdf(
            [
                [
                    "Fictional scholar-",
                    "ship award requirements remain as printed.",
                    "Bourse et financement: les conditions restent inchangées.",
                    "Applicants    must   submit supporting evidence.",
                ],
            ]
        )
    )
    assert result.status == "ok"
    assert result.text == (
        "Fictional scholar-\nship award requirements remain as printed.\n"
        "Bourse et financement: les conditions restent inchangées.\n"
        "Applicants must submit supporting evidence."
    )
    assert_offset_round_trip(result)


def test_table_layout_keeps_cells_on_one_line_per_row() -> None:
    output = BytesIO()
    canvas = Canvas(output, pagesize=(612, 792), invariant=1)
    canvas.setFont("Helvetica", 10)
    rows = [
        ("Item", "Amount", "Timing"),
        ("Tuition", "EUR 12000", "Annual"),
        ("Stipend", "EUR 800", "Monthly"),
    ]
    for row_number, cells in enumerate(rows):
        for x, cell in zip((72, 260, 420), cells, strict=True):
            canvas.drawString(x, 720 - row_number * 18, cell)
    canvas.showPage()
    canvas.save()
    result = extract_pdf_text(output.getvalue())
    assert result.status == "ok"
    assert result.text.splitlines() == [" ".join(row) for row in rows]
    assert result.pages[0].text == result.text
    assert_offset_round_trip(result)


@pytest.mark.parametrize("offset", [-1, 10_000])
def test_locator_rejects_out_of_range_offsets(offset: int) -> None:
    result = extract_pdf_text(
        make_text_pdf([["Full funding is available for eligible applicants."]])
    )
    assert result.status == "ok"
    assert result.locator(offset) is None
    assert result.locator(len(result.text)) is None
