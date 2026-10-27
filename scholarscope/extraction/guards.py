"""Literal URL provenance over selected original passage text; never fetch/repair."""


def url_on_page(url: str, sent_passages: tuple[tuple[str, str], ...]) -> bool:
    """Presence only: not authority, safety, target ownership or semantic support.

    Match within one sent passage, verbatim and case-sensitively. Relative URLs,
    decoded entities, redirects or href-only targets are not inferred/repaired.
    """
    return bool(url) and any(url in text for _, text in sent_passages)
