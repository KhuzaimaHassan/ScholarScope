"""Deterministic passages over unchanged cleaned text and original offset maps.

Passage text is UNTRUSTED page content, including possible instructions aimed at
an LLM. This module never interprets or follows it, verifies evidence, or calls
external services. Changing any segmentation/ID rule requires a version bump.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Literal

from scholarscope.cleaner import CleanedHTML, SourceSpan
from scholarscope.pdf_text import ExtractedPDF, PDFTextSpan

SEGMENTER_VERSION = "1"
SourceRef = SourceSpan | PDFTextSpan
_HEADING = re.compile(r"/h[1-6]\[\d+\](?:/|$)")
_ROW = re.compile(r"/tr\[\d+\](?:/|$)")
_SENTENCE_END = re.compile(r"[.?!;](?=\s)")


@dataclass(frozen=True)
class Passage:
    id: str
    index: int
    start: int
    end: int
    text_hash: str
    section_heading: str | None
    locator: str | None
    source_refs: tuple[SourceRef, ...]
    exceeds_max: bool
    _document_text: str = field(repr=False)

    @property
    def text(self) -> str:
        """Slice the shared immutable document string; never store a passage copy."""
        return self._document_text[self.start : self.end]


@dataclass(frozen=True)
class SegmentedDocument:
    text: str
    passages: tuple[Passage, ...]
    segmenter_version: str
    source_kind: Literal["html", "pdf"]
    unsupported_reason: str | None

    def __post_init__(self) -> None:
        if any(p._document_text is not self.text for p in self.passages):
            raise ValueError("passages must share the document's immutable text object")


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    heading: bool
    table_row: bool
    page: int | None


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    heading: str | None
    page: int | None
    new_passage: bool = False


class _OffsetMap:
    def __init__(self, spans: tuple[SourceRef, ...]) -> None:
        self.spans = spans
        self.starts = tuple(s.start for s in spans)
        self.ends = tuple(s.end for s in spans)

    def overlaps(self, start: int, end: int) -> tuple[SourceRef, ...]:
        return self.spans[bisect_right(self.ends, start) : bisect_left(self.starts, end)]

    def clipped(self, start: int, end: int) -> tuple[SourceRef, ...]:
        refs: list[SourceRef] = []
        for span in self.overlaps(start, end):
            a, b = max(start, span.start), min(end, span.end)
            if isinstance(span, SourceSpan):
                source_start, source_end = span.source_start, span.source_end
                if (
                    source_start is not None
                    and source_end is not None
                    and source_end - source_start == span.end - span.start
                ):
                    source_start += a - span.start
                    source_end -= span.end - b
                # A collapsed whitespace character retains its whole raw range.
                refs.append(SourceSpan(a, b, span.node_path, source_start, source_end))
            else:
                page_start, page_end = span.page_start, span.page_end
                if not span.is_separator:
                    page_start += a - span.start
                    page_end -= span.end - b
                refs.append(
                    PDFTextSpan(a, b, span.page_number, page_start, page_end, span.is_separator)
                )
        return tuple(refs)


def _lines(text: str, offsets: _OffsetMap) -> list[_Line]:
    result: list[_Line] = []
    for match in re.finditer(r"[^\n]+", text):
        if not match.group().strip():
            continue
        refs = offsets.overlaps(match.start(), match.end())
        paths = [s.node_path for s in refs if isinstance(s, SourceSpan)]
        row = any(_ROW.search(path) for path in paths)
        heading = not row and any(_HEADING.search(path) for path in paths)
        page = next(
            (s.page_number for s in refs if isinstance(s, PDFTextSpan) and not s.is_separator), None
        )
        result.append(_Line(match.start(), match.end(), heading, row, page))
    return result


def _ordinary(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    """Break only at sentence/whitespace boundaries; never split a word."""
    if end - start <= limit:
        return [(start, end)]
    result: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor == end:
            break
        if end - cursor <= limit:
            result.append((cursor, end))
            break
        boundary = cursor + limit
        sentences = list(_SENTENCE_END.finditer(text, cursor, boundary + 1))
        cuts = [m.end() for m in sentences if m.end() <= boundary]
        if cuts:
            cut = cuts[-1]
        else:
            spaces = list(re.finditer(r"\s+", text[cursor : boundary + 1]))
            if spaces:
                cut = cursor + spaces[-1].start()
            else:
                following = re.search(r"\s", text[boundary:end])
                cut = boundary + following.start() if following else end
        result.append((cursor, cut))
        cursor = cut
    return result


def _row_ranges(text: str, line: _Line, limit: int, offsets: _OffsetMap) -> list[tuple[int, int]]:
    hard_max = 2 * limit
    if line.end - line.start <= hard_max:
        return [(line.start, line.end)]
    pieces: list[tuple[int, int, bool]] = []
    cursor = line.start
    delimiters = [
        s
        for s in offsets.overlaps(line.start, line.end)
        if isinstance(s, SourceSpan)
        and s.is_separator
        and _ROW.search(s.node_path)
        and text[s.start : s.end] == " | "
    ]
    for delimiter in delimiters:
        a, b = delimiter.start, delimiter.end
        cell = _ordinary(text, cursor, a, limit) if a - cursor > hard_max else [(cursor, a)]
        pieces.extend((s, e, a - cursor > hard_max) for s, e in cell if s < e)
        pieces.append((a, b, False))
        cursor = b
    last = (
        _ordinary(text, cursor, line.end, limit)
        if line.end - cursor > hard_max
        else [(cursor, line.end)]
    )
    pieces.extend((s, e, line.end - cursor > hard_max) for s, e in last if s < e)
    result: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    for a, b, ordinary in pieces:
        if start is not None and (ordinary or b - start > hard_max):
            result.append((start, end))
            start = None
        if start is None:
            start = a
        end = b
        if b - a > hard_max:  # An unbreakable word is the only oversized unit.
            result.append((start, end))
            start = None
    if start is not None:
        result.append((start, end))
    return result


def _units(text: str, lines: list[_Line], limit: int, offsets: _OffsetMap) -> list[_Unit]:
    result: list[_Unit] = []
    section: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.heading and line.end - line.start <= limit:
            headings = [line]
            j = i + 1
            while j < len(lines) and lines[j].heading and lines[j].end - lines[j].start <= limit:
                headings.append(lines[j])
                j += 1
            content = lines[j] if j < len(lines) else None
            groups: list[list[_Line]] = [[]]
            for heading in headings:
                if groups[-1] and heading.end - groups[-1][0].start > 2 * limit:
                    groups.append([])
                groups[-1].append(heading)
            for group in groups[:-1]:
                result.append(
                    _Unit(
                        group[0].start,
                        group[-1].end,
                        text[group[-1].start : group[-1].end],
                        None,
                        True,
                    )
                )
            tail = groups[-1]
            section = text[tail[-1].start : tail[-1].end]
            if content is not None and content.end - tail[0].start <= 2 * limit:
                result.append(_Unit(tail[0].start, content.end, section, None, True))
                i = j + 1
            else:
                result.append(_Unit(tail[0].start, tail[-1].end, section, None, True))
                i = j
            continue
        ranges = (
            _row_ranges(text, line, limit, offsets)
            if line.table_row
            else _ordinary(text, line.start, line.end, limit)
        )
        result.extend(
            _Unit(a, b, section, line.page, line.table_row and line.end - line.start > 2 * limit)
            for a, b in ranges
        )
        i += 1
    return result


def _locator(refs: tuple[SourceRef, ...], kind: Literal["html", "pdf"]) -> str | None:
    if kind == "html":
        return next((r.node_path for r in refs if isinstance(r, SourceSpan)), None)
    pages = [r.page_number for r in refs if isinstance(r, PDFTextSpan) and not r.is_separator]
    if not pages:
        return None
    first, last = min(pages), max(pages)
    return f"p.{first}" if first == last else f"p.{first}-{last}"


def segment(source: CleanedHTML | ExtractedPDF, *, max_chars: int = 1200) -> SegmentedDocument:
    """Keep source text unchanged, grouping bounded structural units left to right."""
    if max_chars < 50:
        raise ValueError("max_chars must be at least 50")
    kind: Literal["html", "pdf"] = "pdf" if isinstance(source, ExtractedPDF) else "html"
    reason = (
        f"PDF status: {source.status}"
        if isinstance(source, ExtractedPDF) and source.status != "ok"
        else None
    )
    if reason is None and not source.text.strip():
        reason = "empty text"
    if reason is not None:
        return SegmentedDocument(source.text, (), SEGMENTER_VERSION, kind, reason)
    offsets = _OffsetMap(source.offset_map)
    units = _units(source.text, _lines(source.text, offsets), max_chars, offsets)
    groups: list[list[_Unit]] = []
    for unit in units:
        if (
            not groups
            or unit.new_passage
            or unit.page != groups[-1][-1].page
            or unit.end - groups[-1][0].start > max_chars
        ):
            groups.append([])
        groups[-1].append(unit)
    passages: list[Passage] = []
    for index, group in enumerate(groups):
        start, end = group[0].start, group[-1].end
        normalized = " ".join(source.text[start:end].split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
        refs = offsets.clipped(start, end)
        passages.append(
            Passage(
                f"p{index:04d}-{digest}",
                index,
                start,
                end,
                digest,
                group[0].heading,
                _locator(refs, kind),
                refs,
                end - start > max_chars,
                source.text,
            )
        )
    return SegmentedDocument(source.text, tuple(passages), SEGMENTER_VERSION, kind, None)


def passage_by_id(doc: SegmentedDocument, passage_id: str) -> Passage | None:
    return next((p for p in doc.passages if p.id == passage_id), None)


def locate(doc: SegmentedDocument, passage_id: str, quote: str) -> tuple[int, int] | None:
    """First exact occurrence in the named passage, as document-level offsets."""
    passage = passage_by_id(doc, passage_id)
    if passage is None or not quote:
        return None
    offset = passage.text.find(quote)
    if offset < 0:
        return None
    start = passage.start + offset
    return start, start + len(quote)
