"""Provider-neutral typed generation. Page passages are untrusted DATA, not policy.

This layer validates shapes, not evidence/support. Extraction (#19) must initialize
verification to not_checked; only the deterministic verifier may promote it.
"""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, Protocol, TypedDict, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

if TYPE_CHECKING:
    from scholarscope.llm.cache import FileCache

T = TypeVar("T", bound=BaseModel)
Status = Literal["ok", "invalid_output", "provider_error", "unavailable"]


@dataclass(frozen=True)
class StructuredRequest(Generic[T]):
    system: str
    task: str
    untrusted_passages: tuple[tuple[str, str], ...]
    response_model: type[T]
    prompt_version: str
    temperature: float = 0.0
    max_output_tokens: int = 2048

    def __post_init__(self) -> None:
        if (
            not isinstance(self.system, str)
            or not isinstance(self.task, str)
            or not self.task.strip()
        ):
            raise ValueError("system must be text and task must be non-empty text")
        if not isinstance(self.response_model, type) or not issubclass(
            self.response_model, BaseModel
        ):
            raise ValueError("response_model must be a Pydantic model class")  # noqa: TRY004 -- API contract
        try:
            self.response_model.model_json_schema()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("response_model must provide a JSON Schema") from None
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature must be finite and between 0 and 2")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer")
        if not isinstance(self.prompt_version, str) or not self.prompt_version.strip():
            raise ValueError("prompt_version must be non-empty")
        if not isinstance(self.untrusted_passages, tuple) or any(
            not isinstance(p, tuple)
            or len(p) != 2
            or not isinstance(p[0], str)
            or not p[0]
            or not isinstance(p[1], str)
            for p in self.untrusted_passages
        ):
            raise ValueError("untrusted_passages must be tuples of passage ID and text")


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class StructuredResponse(Generic[T]):
    status: Status
    parsed: T | None = field(default=None, repr=False)
    raw_text: str | None = field(default=None, repr=False)
    attempts: int = 0
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    usage: Usage = field(default_factory=Usage)
    cached: bool = False
    error: str | None = None


class LLMClient(Protocol):
    def generate_structured(self, request: StructuredRequest[T]) -> StructuredResponse[T]: ...
    def close(self) -> None: ...


class _Identity(TypedDict):
    provider: str
    model: str
    prompt_version: str


def render_user_message(task: str, passages: tuple[tuple[str, str], ...]) -> str:
    """Isolated, minimal data delimiters; NOT prompt-injection hardening (#21).

    Callers supply trusted task/system separately, never interpolate page content
    into them. Passage text is preserved byte-for-character; hostile delimiters
    inside that text remain data and need #21's stronger handling.
    """
    parts = [task, "Return only JSON matching the supplied response schema."]
    for passage_id, text in passages:
        parts.append(
            f"[BEGIN UNTRUSTED DATA passage_id={json.dumps(passage_id)}]\n"
            f"{text}\n[END UNTRUSTED DATA]"
        )
    return "\n\n".join(parts)


def token_count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def schema_nodes(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Visit schema objects, NOT user property names, enum values or defaults."""
    nodes = [schema]
    for key, value in schema.items():
        if key in {"properties", "$defs"} and isinstance(value, dict):
            for child in value.values():
                if isinstance(child, dict):
                    nodes.extend(schema_nodes(child))
        elif key in {"items", "additionalProperties"} and isinstance(value, dict):
            nodes.extend(schema_nodes(value))
        elif key in {"anyOf", "oneOf", "allOf", "prefixItems"} and isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    nodes.extend(schema_nodes(child))
    return nodes


class BaseClient:
    """Shared cache, validation, bounded transport retries, and secret-safe errors.

    max_attempts counts model-output attempts (default 3); each may use at most
    3 transport tries. Response.attempts counts actual sends, including retries.
    No exception text/body/headers is copied into an error or validation prompt.
    """

    provider = "base"

    def __init__(
        self,
        model: str,
        *,
        api_key: SecretStr | None = None,
        http_client: httpx.Client | None = None,
        cache: FileCache | None = None,
        timeout_seconds: float = 30,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be non-empty")
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        self.model = model
        self._key = api_key
        self._http = http_client
        self._owns_http = http_client is None
        self.cache = cache
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.sleeper, self.rng, self.clock = sleeper, rng, clock

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()

    def _contains_secret(self, text: str) -> bool:
        key = self._key.get_secret_value() if self._key is not None else ""
        if not key:
            return False
        if key in text:
            return True
        # JSON escapes must not sneak a credential into parsed output or cache.
        try:
            pending = [json.loads(text)]
        except (ValueError, RecursionError):
            return False
        while pending:
            value = pending.pop()
            if isinstance(value, str) and key in value:
                return True
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return False

    def _capability_error(self, request: StructuredRequest[Any]) -> str | None:
        if self.provider in {"gemini", "groq"} and not (self._key and self._key.get_secret_value()):
            return "API credential not configured"
        return None

    def _endpoint(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {}

    def _payload(self, request: StructuredRequest[Any], user: str) -> dict[str, Any]:
        raise NotImplementedError

    def _extract(self, data: dict[str, Any]) -> tuple[str | None, Usage]:
        raise NotImplementedError

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        delay = (2.0**attempt) + max(0.0, min(1.0, self.rng()))
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                try:
                    when = parsedate_to_datetime(retry_after)
                    seconds = (when - self.clock()).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    seconds = 0
            if math.isfinite(seconds):
                delay = max(delay, seconds)
        return delay

    def _send(
        self, request: StructuredRequest[Any], user: str
    ) -> tuple[str | None, Usage, int, str | None]:
        if self._http is None:
            self._http = httpx.Client(trust_env=False, follow_redirects=False)
        for attempt in range(3):
            retry_after = None
            try:
                response = self._http.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json=self._payload(request, user),
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                error = "transport timeout or connection error"
            except (httpx.HTTPError, httpx.InvalidURL, UnicodeError):
                return None, Usage(), attempt + 1, "HTTP transport failure"
            else:
                status = response.status_code
                if status == 429 or 500 <= status <= 599:
                    error = f"HTTP {status}"
                    retry_after = response.headers.get("Retry-After")
                elif not 200 <= status < 300:
                    return None, Usage(), attempt + 1, f"HTTP {status} (request rejected)"
                else:
                    try:
                        data = response.json()
                        if not isinstance(data, dict):
                            raise TypeError
                        raw, usage = self._extract(data)
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        return None, Usage(), attempt + 1, "invalid provider response envelope"
                    if raw is not None and self._contains_secret(raw):
                        return None, Usage(), attempt + 1, "credential detected in provider output"
                    return raw, usage, attempt + 1, None
            if attempt < 2:
                self.sleeper(self._delay(attempt, retry_after))
        return None, Usage(), 3, error

    def generate_structured(self, request: StructuredRequest[T]) -> StructuredResponse[T]:
        # Recheck even if someone bypassed dataclass construction.
        request.__post_init__()
        common: _Identity = {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": request.prompt_version,
        }
        if self.cache is not None:
            entry = self.cache.get(self.provider, self.model, request)
            if entry is not None and not self._contains_secret(entry.raw_text):
                try:
                    parsed = request.response_model.model_validate_json(entry.raw_text)
                except (ValueError, TypeError, ValidationError):
                    pass
                else:
                    return StructuredResponse(
                        "ok", parsed, entry.raw_text, usage=entry.usage, cached=True, **common
                    )
            if self.cache.mode == "read_only":
                return StructuredResponse(
                    "unavailable", error="cache miss or invalid cached output", **common
                )
        capability = self._capability_error(request)
        if capability:
            return StructuredResponse("unavailable", error=capability, **common)
        user = render_user_message(request.task, request.untrusted_passages)
        attempts, raw, usage = 0, None, Usage()
        for _ in range(self.max_attempts):
            raw, usage, sends, error = self._send(request, user)
            attempts += sends
            if error:
                return StructuredResponse(
                    "provider_error", attempts=attempts, error=error, **common
                )
            try:
                if raw is None:
                    raise ValueError
                parsed = request.response_model.model_validate_json(raw)
            except (ValueError, TypeError, ValidationError):
                user += "\n\nPrevious output failed JSON/Pydantic validation. Return only schema-valid JSON."
            else:
                cache_error = None
                if self.cache is not None and not self.cache.put(
                    self.provider, self.model, request, raw, usage
                ):
                    cache_error = "cache write failed"
                return StructuredResponse(
                    "ok", parsed, raw, attempts, usage=usage, error=cache_error, **common
                )
        return StructuredResponse(
            "invalid_output",
            raw_text=raw,
            attempts=attempts,
            usage=usage,
            error="JSON/Pydantic validation failed",
            **common,
        )
