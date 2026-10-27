"""Advisory, bypassable heuristics. Never filter passages, claims or verification."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from scholarscope.segmenter import Passage


@dataclass(frozen=True)
class SuspiciousPassage:
    passage_id: str
    reasons: tuple[str, ...]


_PATTERNS = tuple(
    (reason, re.compile(pattern, re.IGNORECASE))
    for reason, pattern in (
        (
            "instruction_override",
            r"\b(?:ignore|disregard|forget|override)\b[\s\S]{0,60}\b(?:previous|prior|system|instructions|rules)\b",
        ),
        (
            "fake_role_tag",
            r"<\s*/?\s*(?:system|assistant|tool|developer)\b|\[/?(?:SYSTEM|ASSISTANT|TOOL)\]|<\|(?:im_start|im_end|system|assistant|tool)\|>|(?:^|\n)\s*#{1,6}\s*(?:system|assistant|tool|task)\b",
        ),
        (
            "requested_output",
            r"\b(?:output|return|print|respond)\b[\s\S]{0,80}\b(?:value|only|exact|instead|following|url|image|deadline)\b",
        ),
        (
            "requested_state",
            r"\b(?:set|mark|make)\b[\s\S]{0,60}\b(?:verification|verified|unverified|status|present|absent)\b",
        ),
        (
            "exfiltration",
            r"!\[[^\n\]]{0,120}\]\(https?://[^\s)]+\)|\b(?:reveal|leak|exfiltrate|send)\b[\s\S]{0,100}(?:prompt|https?://)",
        ),
        (
            "passage_header",
            r"\[(?:BEGIN|END) UNTRUSTED DATA|\bpassage_id\s*[=:]|\bp\d{4}-[a-z0-9]{4,}",
        ),
    )
)


def scan_passages(passages: Iterable[Passage]) -> tuple[SuspiciousPassage, ...]:
    """Return document-ordered findings with fixed-order reasons; no side effects."""
    findings = []
    for passage in passages:
        reasons = tuple(reason for reason, pattern in _PATTERNS if pattern.search(passage.text))
        if reasons:
            findings.append(SuspiciousPassage(passage.id, reasons))
    return tuple(findings)
