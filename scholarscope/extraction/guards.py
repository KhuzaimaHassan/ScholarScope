"""URL and numeric presence controls; never fetch, repair or establish support."""

import math
import re
from collections.abc import Mapping


def numeric_candidates(quotes: tuple[str, ...]) -> set[float]:
    """Keep comma and grouped-dot interpretations; strip terminal punctuation."""
    candidates: set[float] = set()
    for quote in quotes:
        for token in re.findall(r"\d[\d.,]*", quote):
            token = token.rstrip(".,")
            interpretations = [token.replace(",", "")]
            if "," in token:
                interpretations.append(token.replace(".", "").replace(",", "."))
            if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", token):
                interpretations.append(token.replace(".", "").replace(",", "."))
            for interpretation in interpretations:
                try:
                    value = float(interpretation)
                except ValueError:
                    continue
                if math.isfinite(value):
                    candidates.add(value)
    return candidates


def numeric_provenance_error(values: Mapping[str, object], quotes: tuple[str, ...]) -> str | None:
    """First missing numeric value only; malformed shapes go to domain validation."""
    candidates = numeric_candidates(quotes)
    for name, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            present = float(value) in candidates
        except OverflowError:
            present = False
        if not present:
            return f"NUMBER_NOT_IN_QUOTE:{name}"
    return None


def url_on_page(url: str, sent_passages: tuple[tuple[str, str], ...]) -> bool:
    """Presence only: not authority, safety, target ownership or semantic support.

    Match within one sent passage, verbatim and case-sensitively. Relative URLs,
    decoded entities, redirects or href-only targets are not inferred/repaired.
    """
    return bool(url) and any(url in text for _, text in sent_passages)
