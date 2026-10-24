"""Pure quote PRESENCE checks, never value support or page instructions.

All page text is untrusted data. Formatting normalization is not character-edit
fuzzy matching: changed digits, words, case and homoglyphs must fail. Inputs and
failed claims are retained unchanged except for recomputed verification state.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from scholarscope.schema import Evidence, RequirementFields, RequirementRecord
from scholarscope.segmenter import Passage, SegmentedDocument

VERIFIER_VERSION = "1"
_REMOVED = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff")
_PUNCTUATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)
_HYPHEN_BREAK = re.compile(r"-\r?\n")


class QuoteOutcome(StrEnum):
    INVALID_QUOTE = "invalid_quote"
    NO_PASSAGE_CITED = "no_passage_cited"
    EXACT = "exact"
    NORMALIZED = "normalized"
    SPANS_PASSAGES = "spans_passages"
    FOUND_IN_OTHER_PASSAGE = "found_in_other_passage"
    NOT_FOUND = "not_found"


_VERIFIED = {QuoteOutcome.EXACT, QuoteOutcome.NORMALIZED, QuoteOutcome.SPANS_PASSAGES}


@dataclass(frozen=True)
class EvidenceResult:
    owner_path: str
    evidence_index: int
    quote: str
    outcome: QuoteOutcome
    matched: tuple[int, int] | None = None
    passage_ids: tuple[str, ...] = ()
    suggested_passage_ids: tuple[str, ...] = ()
    occurrences: int = 0
    ambiguous_location: bool = False
    near_match: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    items: tuple[EvidenceResult, ...]
    totals: dict[QuoteOutcome, int]
    verifier_version: str = VERIFIER_VERSION


@dataclass(frozen=True)
class _Character:
    char: str
    start: int
    end: int


@dataclass(frozen=True)
class _Normalized:
    text: str
    ranges: tuple[tuple[int, int], ...]


def _nfkc(characters: list[_Character]) -> list[_Character]:
    """Compatibility decomposition, canonical ordering/composition WITH origins.

    Per-codepoint NFKC alone is wrong for combining sequences and Hangul. Stable
    canonical ordering and NFC pair composition implement full-string NFKC while
    retaining the union of original ranges for every composed character.
    """
    ordered: list[_Character] = []
    marks: list[_Character] = []
    for original in characters:
        for char in unicodedata.normalize("NFKD", original.char):
            unit = _Character(char, original.start, original.end)
            if unicodedata.combining(char):
                marks.append(unit)
            else:
                ordered.extend(sorted(marks, key=lambda c: unicodedata.combining(c.char)))
                marks.clear()
                ordered.append(unit)
    ordered.extend(sorted(marks, key=lambda c: unicodedata.combining(c.char)))
    result: list[_Character] = []
    starter: int | None = None
    last_class = 0
    for unit in ordered:
        combining_class = unicodedata.combining(unit.char)
        if starter is not None and (last_class < combining_class or last_class == 0):
            previous = result[starter]
            composed = unicodedata.normalize("NFC", previous.char + unit.char)
            if len(composed) == 1:
                result[starter] = _Character(
                    composed, min(previous.start, unit.start), max(previous.end, unit.end)
                )
                continue
        if combining_class == 0:
            starter = len(result)
        result.append(unit)
        last_class = combining_class
    return result


def _normalize(text: str) -> _Normalized:
    # Only a literal hyphen immediately followed by LF/CRLF joins a broken word.
    # A hyphen plus spaces plus newline remains a hyphen, not an invented word.
    deleted = {i for m in _HYPHEN_BREAK.finditer(text) for i in range(m.start(), m.end())}
    characters = [
        _Character(char, i, i + 1)
        for i, char in enumerate(text)
        if i not in deleted and char not in _REMOVED
    ]
    output: list[_Character] = []
    for unit in _nfkc(characters):
        char = unit.char.translate(_PUNCTUATION)
        if char.isspace():
            if not output:
                continue
            if output[-1].char == " ":
                previous = output[-1]
                output[-1] = _Character(" ", previous.start, unit.end)
                continue
            char = " "
        output.append(_Character(char, unit.start, unit.end))
    if output and output[-1].char == " ":
        output.pop()
    return _Normalized("".join(c.char for c in output), tuple((c.start, c.end) for c in output))


def _find_all(text: str, quote: str) -> Iterator[int]:
    cursor = 0
    while (start := text.find(quote, cursor)) >= 0:
        yield start
        cursor = start + 1  # Count overlapping occurrences too.


class _Matcher:
    def __init__(self, doc: SegmentedDocument) -> None:
        self.doc = doc
        self.normalized = _normalize(doc.text)
        self.passages = {p.id: p for p in doc.passages}

    def matches(self, quote: str, normalized_quote: str) -> list[tuple[int, int]]:
        matches: set[tuple[int, int]] = set()
        for i in _find_all(self.normalized.text, normalized_quote):
            origins = self.normalized.ranges[i : i + len(normalized_quote)]
            start = min(a for a, _ in origins)
            end = max(b for _, b in origins)
            # Do not certify half a compatibility expansion (e.g. one letter of
            # a ligature), or a reordered sequence whose source slice differs.
            if _normalize(self.doc.text[start:end]).text == normalized_quote:
                matches.add((start, end))
        for i in _find_all(self.doc.text, quote):
            exact = (i, i + len(quote))
            # Boundary whitespace/removed characters can give an exact and a
            # narrower normalized range for ONE occurrence, not two locations.
            matches = {m for m in matches if not (exact[0] <= m[0] and m[1] <= exact[1])}
            matches.add(exact)
        return sorted(matches)

    def touched(self, match: tuple[int, int]) -> tuple[str, ...]:
        start, end = match
        return tuple(p.id for p in self.doc.passages if start < p.end and end > p.start)

    def suggestions(self, matches: list[tuple[int, int]]) -> tuple[str, ...]:
        ids = {pid for match in matches for pid in self.touched(match)}
        return tuple(p.id for p in self.doc.passages if p.id in ids)

    def select(
        self, matches: list[tuple[int, int]], evidence: Evidence
    ) -> tuple[tuple[int, int], bool]:
        before = _normalize(evidence.context_before or "").text
        after = _normalize(evidence.context_after or "").text
        contextual = [
            match
            for match in matches
            if (not before or _normalize(self.doc.text[: match[0]]).text.endswith(before))
            and (not after or _normalize(self.doc.text[match[1] :]).text.startswith(after))
        ]
        if (before or after) and len(contextual) == 1:
            return contextual[0], False
        # Context is a locator hint, not evidence: absent/conflicting context
        # cannot turn real quote presence into absence. Prefer verbatim, then first.
        exact = [m for m in matches if self.doc.text[m[0] : m[1]] == evidence.quote]
        return (exact or matches)[0], len(matches) > 1

    def check(self, owner: str, index: int, evidence: Evidence) -> EvidenceResult:
        quote = evidence.quote
        normalized = _normalize(quote).text
        if (
            len(normalized) < 6
            or len(_TOKENS.findall(normalized)) < 2
            or "..." in quote
            or "…" in quote
            or "..." in normalized
        ):
            return EvidenceResult(owner, index, quote, outcome=QuoteOutcome.INVALID_QUOTE)
        matches = self.matches(quote, normalized)
        passage = self.passages.get(evidence.passage_id or "")
        if passage is None:
            return EvidenceResult(
                owner,
                index,
                quote,
                outcome=QuoteOutcome.NO_PASSAGE_CITED,
                suggested_passage_ids=self.suggestions(matches) if len(matches) == 1 else (),
                occurrences=len(matches),
                ambiguous_location=len(matches) > 1,
            )
        inside = [m for m in matches if passage.start <= m[0] and m[1] <= passage.end]
        exact_inside = [m for m in inside if self.doc.text[m[0] : m[1]] == quote]
        overlapping = [m for m in matches if self._crosses(m, passage)]
        candidates = exact_inside or inside or overlapping
        if candidates:
            match, ambiguous = self.select(candidates, evidence)
            outcome = (
                QuoteOutcome.SPANS_PASSAGES
                if not inside
                else QuoteOutcome.EXACT
                if self.doc.text[match[0] : match[1]] == quote
                else QuoteOutcome.NORMALIZED
            )
            return EvidenceResult(
                owner,
                index,
                quote,
                outcome=outcome,
                matched=match,
                passage_ids=self.touched(match),
                occurrences=len(candidates),
                ambiguous_location=ambiguous,
            )
        return EvidenceResult(
            owner,
            index,
            quote,
            outcome=QuoteOutcome.FOUND_IN_OTHER_PASSAGE if matches else QuoteOutcome.NOT_FOUND,
            suggested_passage_ids=self.suggestions(matches),
            occurrences=len(matches),
            ambiguous_location=len(matches) > 1,
        )

    def _crosses(self, match: tuple[int, int], passage: Passage) -> bool:
        start, end = match
        # Starting/ending *inside* the cited passage is required. Merely enclosing
        # it (both endpoints outside) is not presence in the cited window.
        endpoint_inside = passage.start <= start < passage.end or passage.start < end <= passage.end
        return endpoint_inside and len(self.touched(match)) > 1


def verify_record(
    record: RequirementRecord, doc: SegmentedDocument
) -> tuple[RequirementRecord, VerificationReport]:
    """Return an independent record; recompute ALL claim states, never trust input.

    Every quote on an item must pass. Evidence, values, IDs, context, confidence
    and metadata are never rewritten, even when an item fails verification.
    """
    result = record.model_copy(deep=True)
    matcher = _Matcher(doc)
    items: list[EvidenceResult] = []
    owners = [
        (f"fields.{name}", getattr(result.fields, name))
        for name in sorted(RequirementFields.model_fields)
    ]
    owners.extend((f"deadlines[{i}]", item) for i, item in enumerate(result.deadlines))
    owners.extend((f"conditions[{i}]", item) for i, item in enumerate(result.conditions))
    for path, item in owners:
        checked = [matcher.check(path, i, evidence) for i, evidence in enumerate(item.evidence)]
        item.verification = (
            "not_checked"
            if not checked
            else "verified"
            if all(quote.outcome in _VERIFIED for quote in checked)
            else "unverified"
        )
        items.extend(checked)
    totals = {outcome: sum(item.outcome == outcome for item in items) for outcome in QuoteOutcome}
    return result, VerificationReport(tuple(items), totals)
