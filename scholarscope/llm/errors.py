"""In-memory provider diagnostics; never serialize these into persistent artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

FailureCategory = Literal[
    "rate_limited", "server_error", "bad_request", "timeout", "schema_rejected", "other"
]


@dataclass(frozen=True)
class FailureDetail:
    category: FailureCategory
    http_status: int | None = None
    message: str | None = field(default=None, repr=False)


def redact_secrets(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Redact known credentials plus conservative credential/token-shaped strings."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(
        r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+",
        lambda match: (
            "[redacted-url]" if "@" in match[0].split("/", 3)[2] else match[0].split("?", 1)[0]
        ),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", text)
    text = re.sub(
        r"(?i)\b((?:api[_-]?key|key|access[_-]?token|token|secret|password)\s*[:=]\s*)"
        r"[\"']?[^\s,;\"']+",
        r"\1[redacted]",
        text,
    )
    return re.sub(
        r"\b(?:AIza[\w-]+|gsk_[\w-]+|sk-[\w-]+|[A-Za-z0-9_+=/-]{24,})\b",
        "[redacted]",
        text,
    )


def sanitize_message(
    message: str | None, *, request_texts: tuple[str, ...], secrets: tuple[str, ...] = ()
) -> str | None:
    if message is None:
        return None
    message = redact_secrets(message, secrets)
    # Check before whitespace collapse/truncation, including late message echoes.
    if any(
        message[i : i + 20] in source
        for i in range(max(0, len(message) - 19))
        for source in request_texts
    ):
        return "[withheld: matched request text]"
    return " ".join(message.split())[:300]


def provider_failure(
    data: object,
    http_status: int,
    *,
    request_texts: tuple[str, ...],
    secrets: tuple[str, ...] = (),
) -> FailureDetail:
    # Only a structured message field is eligible; never stringify the body.
    error = data.get("error") if isinstance(data, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(message, str):
        message = None
    code = error.get("code") if isinstance(error, dict) else None
    schema_description = " ".join(
        part
        for part in (
            message,
            code,
            error.get("type") if isinstance(error, dict) else None,
        )
        if isinstance(part, str)
    )
    category: FailureCategory = "other"
    if re.search(
        r"(?is)(schema.*(?:invalid|complex|unsupported|reject|too (?:large|many)|exceed|limit)"
        r"|(?:invalid|complex|unsupported|reject|too (?:large|many)).*schema)",
        schema_description,
    ):
        category = "schema_rejected"
    elif http_status == 429 or code == 429:
        category = "rate_limited"
    elif 500 <= http_status <= 599 or (type(code) is int and 500 <= code <= 599):
        category = "server_error"
    elif 400 <= http_status <= 499 or (type(code) is int and 400 <= code <= 499):
        category = "bad_request"
    return FailureDetail(
        category,
        http_status,
        sanitize_message(message, request_texts=request_texts, secrets=secrets),
    )
