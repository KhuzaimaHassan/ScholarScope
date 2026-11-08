"""URL and numeric presence controls; never fetch, repair or establish support."""

import math
import re
from collections.abc import Mapping

# English-only category provenance, covering every non-"other" FundingCoverage item.
# Match on original quotes at word starts; this is not semantic support or translation.
FUNDING_ITEM_TERMS: dict[str, tuple[str, ...]] = {
    "tuition": ("tuition", "fee"),
    "stipend": ("stipend", "allowance", "living", "maintenance", "salary", "monthly"),
    "travel": ("travel", "flight", "airfare", "ticket", "transport"),
    "insurance": ("insurance",),
    "housing": ("housing", "accommodation", "dormitor", "lodging", "rent", "room and board"),
    "visa": ("visa",),
}


def funding_item_term_error(item: str, quotes: tuple[str, ...]) -> str | None:
    """English word-start presence only; other/malformed categories go to domain checks."""
    terms = FUNDING_ITEM_TERMS.get(item)
    if terms is None:
        return None
    if any(
        re.search(r"\b" + re.escape(term), quote, re.IGNORECASE)
        for quote in quotes
        for term in terms
    ):
        return None
    return f"ITEM_TERM_NOT_IN_QUOTE:{item}"


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
