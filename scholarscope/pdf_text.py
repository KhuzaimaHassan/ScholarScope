"""Extract text PDF pages without OCR, with traceable normalized-text offsets."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from pypdf import PageObject, PdfReader
from pypdf.errors import DependencyError, FileNotDecryptedError, WrongPasswordError
from pypdf.generic import ArrayObject, NullObject, StreamObject

# Bump whenever extraction behavior changes; snapshot hashes depend on these rules.
PDF_EXTRACTOR_VERSION = "1"

PDFStatus = Literal["ok", "scanned_unsupported", "encrypted_unsupported", "invalid"]
MIN_CHARACTERS_PER_PAGE = 25


@dataclass(frozen=True)
class PDFPage:
    """Normalized extracted text for one physical, one-based PDF page."""

    page_number: int
    text: str


@dataclass(frozen=True)
class PDFTextSpan:
    """Map text[start:end] to pages[page_number - 1].text[page_start:page_end].

    Generated page separators have a zero-width range at the preceding page's
    end, with is_separator=True. They are formatting, not quoted page characters.
    All indices are half-open Python character offsets in normalized text.
    """

    start: int
    end: int
    page_number: int
    page_start: int
    page_end: int
    is_separator: bool = False


@dataclass(frozen=True)
class ExtractedPDF:
    """Immutable extraction outcome; unsupported/invalid documents expose no text."""

    text: str = ""
    pages: tuple[PDFPage, ...] = ()
    offset_map: tuple[PDFTextSpan, ...] = ()
    status: PDFStatus = "invalid"
    page_count: int = 0

    def locator(self, offset: int) -> str | None:
        """Return e.g. 'p.3', or None for an out-of-range/unavailable offset."""

        return locator(self, offset)


def locator(extracted: ExtractedPDF, offset: int) -> str | None:
    """Locate an offset; generated page breaks belong to the preceding text page."""

    for span in extracted.offset_map:
        if span.start <= offset < span.end:
            return f"p.{span.page_number}"
    return None


def _normalize_whitespace(text: str) -> str:
    # Preserve extracted line boundaries and hyphens, collapsing whitespace only.
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _assemble(pages: tuple[PDFPage, ...]) -> ExtractedPDF:
    parts: list[str] = []
    spans: list[PDFTextSpan] = []
    position = 0
    previous: PDFPage | None = None
    for page in pages:
        if not page.text:
            continue
        if previous is not None:
            parts.append("\n\n")
            spans.append(
                PDFTextSpan(
                    position,
                    position + 2,
                    previous.page_number,
                    len(previous.text),
                    len(previous.text),
                    is_separator=True,
                )
            )
            position += 2
        parts.append(page.text)
        end = position + len(page.text)
        spans.append(PDFTextSpan(position, end, page.page_number, 0, len(page.text)))
        position = end
        previous = page
    return ExtractedPDF("".join(parts), pages, tuple(spans), "ok", len(pages))


def _extract_page(page: PageObject, page_number: int) -> PDFPage:
    # Some pypdf versions silently treat invalid /Contents types as a blank page.
    # Validate the PDF stream/array contract so malformed pages stay invalid.
    contents = page.get("/Contents")
    if contents is None:
        return PDFPage(page_number, "")
    contents = contents.get_object()
    if isinstance(contents, NullObject):
        return PDFPage(page_number, "")
    streams = contents if isinstance(contents, ArrayObject) else [contents]
    if any(not isinstance(stream.get_object(), StreamObject) for stream in streams):
        raise ValueError("PDF page /Contents must be a stream or an array of streams")
    text = (
        page.extract_text(
            extraction_mode="layout",
            layout_mode_space_vertically=False,
            layout_mode_strip_rotated=False,
        )
        or ""
    )
    return PDFPage(page_number, _normalize_whitespace(text))


def extract_pdf_text(data: bytes) -> ExtractedPDF:
    """Extract page text using pypdf's layout mode; malformed data never escapes.

    Fewer than 25 non-whitespace characters per page on average is treated as
    scanned_unsupported (including blank/zero-page PDFs). Password-protected PDFs
    are unsupported unless the empty password opens them. No OCR, wording repair,
    translation or de-hyphenation is performed.
    """

    page_count = 0
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            # The page tree cannot safely be inspected before successful decryption.
            return ExtractedPDF(status="encrypted_unsupported")
        page_count = len(reader.pages)
        pages = tuple(
            _extract_page(page, number) for number, page in enumerate(reader.pages, start=1)
        )
        characters = sum(sum(not character.isspace() for character in page.text) for page in pages)
        if page_count == 0 or characters < MIN_CHARACTERS_PER_PAGE * page_count:
            return ExtractedPDF(
                pages=tuple(PDFPage(page.page_number, "") for page in pages),
                status="scanned_unsupported",
                page_count=page_count,
            )
        return _assemble(pages)
    except (DependencyError, FileNotDecryptedError, WrongPasswordError):
        return ExtractedPDF(status="encrypted_unsupported", page_count=page_count)
    except Exception:  # noqa: BLE001 -- malformed PDF input must never raise.
        # Public untrusted-input boundary: parser/stream/codec failures become an
        # invalid outcome, with no partially extracted text available downstream.
        return ExtractedPDF(status="invalid", page_count=page_count)
