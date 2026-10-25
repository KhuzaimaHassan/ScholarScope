"""Hand-written synthetic envelopes and dummy credentials; no real sockets."""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from scholarscope.llm import (
    FakeClient,
    LLMConfig,
    StructuredRequest,
    build_client,
    render_user_message,
)
from scholarscope.llm.base import BaseClient, Usage
from scholarscope.llm.cache import FileCache, cache_key
from scholarscope.llm.gemini import GeminiClient, unsupported_keywords
from scholarscope.llm.groq import GroqClient
from scholarscope.llm.ollama import OllamaClient
from scholarscope.schema import RequirementRecord

DUMMY_CREDENTIAL = "synthetic-credential-marker-NOT-A-REAL-KEY"
PROVIDERS = ("gemini", "groq", "ollama")
CLIENTS: dict[str, type[BaseClient]] = {
    "gemini": GeminiClient,
    "groq": GroqClient,
    "ollama": OllamaClient,
}
MODELS = {"gemini": "synthetic-model", "groq": "openai/gpt-oss-20b", "ollama": "synthetic-model"}


class Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    value: int


class OtherAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    value: int
    note: str


@pytest.fixture(autouse=True)
def forbid_real_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Real socket/DNS attempt forbidden in LLM tests")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    for name in [
        "LLM_PROVIDER",
        "LLM_MODEL",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OLLAMA_BASE_URL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_CACHE_MODE",
    ]:
        monkeypatch.delenv(name, raising=False)


def request(**changes: Any) -> StructuredRequest[Answer]:
    return StructuredRequest(
        **{
            "system": "Trusted system rule.",
            "task": "Return a fictional integer value.",
            "untrusted_passages": (("p0000-fiction", "Synthetic untrusted source text."),),
            "response_model": Answer,
            "prompt_version": "test-1",
            **changes,
        }
    )


def envelope(provider: str, raw: str, *, usage: bool = True) -> dict[str, Any]:
    if provider == "gemini":
        return {
            "candidates": [{"content": {"parts": [{"text": raw}]}}],
            **(
                {"usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7}}
                if usage
                else {}
            ),
        }
    if provider == "groq":
        return {
            "choices": [{"message": {"content": raw}}],
            **({"usage": {"prompt_tokens": 11, "completion_tokens": 7}} if usage else {}),
        }
    return {
        "message": {"content": raw},
        "done": True,
        **({"prompt_eval_count": 11, "eval_count": 7} if usage else {}),
    }


def client_for(
    provider: str, outputs: list[Any], **options: Any
) -> tuple[BaseClient, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        item = outputs[min(len(requests) - 1, len(outputs) - 1)]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=envelope(provider, item))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = CLIENTS[provider](
        MODELS[provider],
        api_key=SecretStr(DUMMY_CREDENTIAL),
        http_client=http,
        sleeper=sleeps.append,
        rng=lambda: 0.25,
        **options,
    )
    return client, requests, sleeps


@pytest.mark.parametrize("provider", PROVIDERS)
def test_success_parse_usage_and_native_request_shape(provider: str) -> None:
    client, requests, _ = client_for(provider, ['{"value": 3}'])
    req = request(temperature=0.25, max_output_tokens=99)
    response = client.generate_structured(req)
    assert response.status == "ok" and response.parsed == Answer(value=3)
    assert response.raw_text == '{"value": 3}' and response.attempts == 1
    assert response.provider == provider and response.prompt_version == req.prompt_version
    assert response.usage == Usage(input_tokens=11, output_tokens=7)
    body = json.loads(requests[0].content)
    schema = Answer.model_json_schema()
    assert DUMMY_CREDENTIAL not in str(requests[0].url)
    if provider == "gemini":
        config = body["generationConfig"]
        assert config == {
            "responseJsonSchema": schema,
            "responseMimeType": "application/json",
            "temperature": 0.25,
            "maxOutputTokens": 99,
        }
        assert (
            "responseSchema" not in config
            and unsupported_keywords(config["responseJsonSchema"]) == ()
        )
        assert body["systemInstruction"]["parts"][0]["text"] == req.system
        assert requests[0].headers["x-goog-api-key"] == DUMMY_CREDENTIAL
        assert requests[0].url.path.endswith("/models/synthetic-model:generateContent")
        user = body["contents"][0]["parts"][0]["text"]
    else:
        assert body["messages"][0] == {"role": "system", "content": req.system}
        user = body["messages"][1]["content"]
        if provider == "groq":
            assert body["response_format"]["json_schema"] == {
                "name": "structured_response",
                "schema": schema,
                "strict": True,
            }
            assert body["temperature"] == 0.25 and body["max_completion_tokens"] == 99
            assert requests[0].headers["Authorization"] == f"Bearer {DUMMY_CREDENTIAL}"
        else:
            assert body["format"] == schema and body["stream"] is False
            assert body["options"] == {"temperature": 0.25, "num_predict": 99}
            assert requests[0].url.path == "/api/chat"
    assert req.task in user and req.untrusted_passages[0][1] in user


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("bad", ["not JSON", '{"value": "wrong type"}', '{"value": 1, "extra": 2}'])
def test_invalid_output_retries_and_always_validates_locally(provider: str, bad: str) -> None:
    client, requests, sleeps = client_for(provider, [bad, '{"value": 4}'])
    response = client.generate_structured(request())
    assert response.status == "ok" and response.parsed == Answer(value=4) and response.attempts == 2
    assert b"Previous output failed JSON/Pydantic validation" in requests[1].content
    assert sleeps == []  # Validation retries do not incur transport backoff.


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("raw", ["not JSON", '{"value": "wrong type"}'])
def test_exhausted_model_validation_keeps_last_raw(provider: str, raw: str) -> None:
    client, requests, _ = client_for(provider, [raw])
    response = client.generate_structured(request())
    assert response.status == "invalid_output" and response.parsed is None
    assert response.raw_text == raw and response.attempts == len(requests) == 3


@pytest.mark.parametrize("provider", PROVIDERS)
def test_429_then_success_honors_retry_after(provider: str) -> None:
    client, requests, sleeps = client_for(
        provider,
        [httpx.Response(429, headers={"Retry-After": "5"}, text=DUMMY_CREDENTIAL), '{"value": 5}'],
    )
    response = client.generate_structured(request())
    assert response.status == "ok" and response.attempts == len(requests) == 2
    assert sleeps == [5]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_retry_after_http_date(provider: str) -> None:
    client, _, sleeps = client_for(
        provider,
        [
            httpx.Response(429, headers={"Retry-After": "Sun, 25 Oct 2026 00:00:08 GMT"}),
            '{"value": 5}',
        ],
        clock=lambda: datetime(2026, 10, 25, tzinfo=UTC),
    )
    assert client.generate_structured(request()).status == "ok"
    assert sleeps == [8]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("code", [500, 503])
def test_5xx_exhausted_transport_and_exponential_jitter(provider: str, code: int) -> None:
    client, requests, sleeps = client_for(provider, [httpx.Response(code, text=DUMMY_CREDENTIAL)])
    response = client.generate_structured(request())
    assert response.status == "provider_error" and response.attempts == len(requests) == 3
    assert str(code) in (response.error or "") and DUMMY_CREDENTIAL not in repr(response)
    assert response.raw_text is None and sleeps == [1.25, 2.25]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("code", [400, 401, 403])
def test_request_or_schema_rejection_never_retried_or_downgraded(provider: str, code: int) -> None:
    client, requests, sleeps = client_for(
        provider, [httpx.Response(code, json={"error": DUMMY_CREDENTIAL})]
    )
    response = client.generate_structured(request())
    assert response.status == "provider_error" and response.attempts == len(requests) == 1
    assert str(code) in (response.error or "") and sleeps == []
    assert DUMMY_CREDENTIAL not in repr(response) and response.raw_text is None


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_timeout_and_connection_errors_are_sanitized_and_bounded(
    provider: str, error_type: type[Exception]
) -> None:
    client, requests, sleeps = client_for(provider, [error_type(DUMMY_CREDENTIAL)])
    response = client.generate_structured(request())
    assert response.status == "provider_error" and response.attempts == len(requests) == 3
    assert DUMMY_CREDENTIAL not in (response.error or "") and sleeps == [1.25, 2.25]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_unknown_usage_and_malformed_provider_envelope(provider: str) -> None:
    client, _, _ = client_for(
        provider, [httpx.Response(200, json=envelope(provider, '{"value": 1}', usage=False))]
    )
    assert client.generate_structured(request()).usage == Usage()
    client, _, _ = client_for(provider, [httpx.Response(200, content=b"not a JSON envelope")])
    assert client.generate_structured(request()).status == "provider_error"


def test_groq_json_object_fallback_is_selected_before_call_and_validated() -> None:
    client, calls, _ = client_for("groq", ['{"value": "bad"}', '{"value": 8}'])
    client.model = "unlisted-synthetic-model"
    response = client.generate_structured(request())
    assert response.status == "ok" and response.attempts == 2
    body = json.loads(calls[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert "Response JSON Schema:" in body["messages"][1]["content"]
    assert '"value"' in body["messages"][1]["content"]


def test_groq_best_effort_preserves_optional_schema_without_rewriting() -> None:
    class OptionalAnswer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: int = 1

    client, calls, _ = client_for("groq", ['{"value": 8}'])
    response = client.generate_structured(request(response_model=OptionalAnswer))
    assert response.status == "ok"
    assert json.loads(calls[0].content)["response_format"]["json_schema"] == {
        "name": "structured_response",
        "strict": False,
        "schema": OptionalAnswer.model_json_schema(),
    }


@pytest.mark.parametrize(
    "keyword,schema",
    [
        ("default", {"type": "integer", "default": 1}),
        ("minLength", {"type": "string", "minLength": 1}),
        ("maxLength", {"type": "string", "maxLength": 5}),
        ("pattern", {"type": "string", "pattern": "a"}),
        ("const", {"type": "integer", "const": 1}),
        ("discriminator", {"oneOf": [], "discriminator": {}}),
        ("exclusiveMinimum", {"type": "integer", "exclusiveMinimum": 0}),
    ],
)
def test_gemini_documented_subset_guard(keyword: str, schema: dict[str, Any]) -> None:
    assert unsupported_keywords(schema) == (keyword,)


def test_gemini_unsupported_schema_is_not_silently_stripped_or_sent() -> None:
    class ConstrainedAnswer(BaseModel):
        value: str = Field(min_length=2)

    client, calls, _ = client_for("gemini", ['{"value": "ok"}'])
    original = ConstrainedAnswer.model_json_schema()
    response = client.generate_structured(request(response_model=ConstrainedAnswer))
    assert response.status == "unavailable" and response.attempts == 0 and calls == []
    assert ConstrainedAnswer.model_json_schema() == original
    assert "minLength" in unsupported_keywords(original)
    assert (
        unsupported_keywords({"type": "object", "properties": {"default": {"type": "string"}}})
        == ()
    )


def test_requirement_record_schema_stays_unchanged_and_gemini_refuses_unsupported_keywords() -> (
    None
):
    client, calls, _ = client_for("gemini", ["{}"])
    before = RequirementRecord.model_json_schema()
    result = client.generate_structured(request(response_model=RequirementRecord))
    assert result.status == "unavailable" and calls == []
    assert "minLength" in unsupported_keywords(before)
    assert RequirementRecord.model_json_schema() == before


@pytest.mark.parametrize("provider", PROVIDERS)
def test_json_escaped_credential_cannot_enter_output_or_cache(
    provider: str, tmp_path: Path
) -> None:
    escaped = "".join(f"\\u{ord(char):04x}" for char in DUMMY_CREDENTIAL)
    raw = '{"value": "' + escaped + '"}'
    client, _, _ = client_for(provider, [raw], cache=FileCache(tmp_path))
    result = client.generate_structured(request())
    assert result.status == "provider_error" and result.raw_text is None
    assert list(tmp_path.iterdir()) == []


def test_cache_atomic_write_no_temporary_files_and_corrupt_read_only_miss(tmp_path: Path) -> None:
    cache = FileCache(tmp_path / "entries")
    assert cache.put("fake", "fake-v1", request(), '{"value": 1}', Usage())
    paths = list(cache.directory.iterdir())
    assert len(paths) == 1 and paths[0].suffix == ".json"
    paths[0].write_text("corrupt JSON")
    fake = FakeClient(
        responses=['{"value": 2}'], cache=FileCache(cache.directory, mode="read_only")
    )
    assert fake.generate_structured(request()).status == "unavailable" and fake.calls == 0
    off = FakeClient(responses=['{"value": 2}'], cache=FileCache(tmp_path / "off", mode="off"))
    assert off.generate_structured(request()).status == "ok"
    assert not (tmp_path / "off").exists()


def test_connection_guard_really_blocks_calls_before_network() -> None:
    with pytest.raises(AssertionError, match="Real socket"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_cache_hit_revalidates_and_avoids_call(provider: str, tmp_path: Path) -> None:
    cache = FileCache(tmp_path)
    client, calls, _ = client_for(provider, ['{"value": 3}'], cache=cache)
    first = client.generate_structured(request())
    second = client.generate_structured(request())
    assert first.status == second.status == "ok" and second.cached and second.attempts == 0
    assert len(calls) == 1 and second.parsed == first.parsed and second.usage == first.usage
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert set(data) == {"raw_text", "usage"}
    assert DUMMY_CREDENTIAL not in files[0].read_text()
    # Valid cache envelope, invalid model content: never trust a formerly cached result.
    files[0].write_text(json.dumps({"raw_text": '{"value": "bad"}', "usage": {}}))
    cache.mode = "read_only"
    assert client.generate_structured(request()).status == "unavailable" and len(calls) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_read_only_miss_never_calls_and_off_never_writes(provider: str, tmp_path: Path) -> None:
    client, calls, _ = client_for(
        provider, ['{"value": 3}'], cache=FileCache(tmp_path, mode="read_only")
    )
    assert client.generate_structured(request()).status == "unavailable" and calls == []
    client.cache = FileCache(tmp_path, mode="off")
    assert client.generate_structured(request()).status == "ok"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        {"system": "Other trusted system"},
        {"task": "Other task"},
        {"untrusted_passages": (("different-id", "Synthetic untrusted source text."),)},
        {"untrusted_passages": (("p0000-fiction", "Different text"),)},
        {"response_model": OtherAnswer},
        {"temperature": 0.5},
        {"max_output_tokens": 99},
        {"prompt_version": "test-2"},
    ],
)
def test_each_request_component_changes_cache_key(change: dict[str, Any]) -> None:
    original = request()
    first = cache_key("fake", "fake-v1", original)
    assert len(first) == 64 and first == first.lower()
    assert cache_key("fake", "fake-v1", replace(original, **change)) != first
    assert cache_key("other", "fake-v1", original) != first
    assert cache_key("fake", "other-model", original) != first


@pytest.mark.parametrize("provider", PROVIDERS)
def test_invalid_output_never_cached(provider: str, tmp_path: Path) -> None:
    client, _, _ = client_for(provider, ["not JSON"], cache=FileCache(tmp_path))
    assert client.generate_structured(request()).status == "invalid_output"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_secret_hygiene_errors_logs_response_and_cache(
    provider: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, _, _ = client_for(
        provider, [httpx.Response(400, text=DUMMY_CREDENTIAL)], cache=FileCache(tmp_path)
    )
    result = client.generate_structured(request())
    assert DUMMY_CREDENTIAL not in repr(client) + repr(result) + caplog.text
    client, _, _ = client_for(
        provider, [json.dumps({"value": DUMMY_CREDENTIAL})], cache=FileCache(tmp_path)
    )
    result = client.generate_structured(request())
    assert result.status == "provider_error" and result.raw_text is None
    assert DUMMY_CREDENTIAL not in repr(result) + (result.error or "") + caplog.text
    assert list(tmp_path.iterdir()) == []


def test_config_env_secrets_and_config_swap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", DUMMY_CREDENTIAL)
    monkeypatch.setenv("GROQ_API_KEY", DUMMY_CREDENTIAL)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "9.5")
    monkeypatch.setenv("LLM_CACHE_MODE", "read_only")
    for provider in [*PROVIDERS, "fake"]:
        monkeypatch.setenv("LLM_PROVIDER", provider)
        monkeypatch.setenv("LLM_MODEL", "synthetic-model")
        config = LLMConfig.from_env()
        assert config.timeout_seconds == 9.5 and config.cache_mode == "read_only"
        assert isinstance(config.gemini_api_key, SecretStr)
        assert (
            DUMMY_CREDENTIAL
            not in repr(config) + str(config) + repr(config.model_dump()) + config.model_dump_json()
        )
        client = build_client(config, cache_dir=tmp_path)
        assert isinstance(client, FakeClient if provider == "fake" else CLIENTS[provider])
        assert client.generate_structured(request()).status == "unavailable"
        client.close()
    with pytest.raises(ValidationError) as exc:
        LLMConfig(gemini_api_key=SecretStr(DUMMY_CREDENTIAL), timeout_seconds=-1)
    assert DUMMY_CREDENTIAL not in str(exc.value) + repr(exc.value)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://user:password@example.invalid", "http://localhost/?x=y"]
)
def test_invalid_ollama_base_url_has_sanitized_error(url: str) -> None:
    with pytest.raises(ValidationError) as exc:
        LLMConfig(ollama_base_url=url)
    assert url not in str(exc.value)


@pytest.mark.parametrize(
    "change",
    [
        {"task": " "},
        {"response_model": int},
        {"response_model": Answer(value=1)},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"temperature": float("nan")},
        {"temperature": True},
        {"max_output_tokens": 0},
        {"prompt_version": ""},
        {"untrusted_passages": [("id", "text")]},
    ],
)
def test_invalid_requests_raise_value_error(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        request(**change)


def test_render_preserves_passages_and_keeps_task_separate() -> None:
    passages = (
        ("id-one", "  Synthetic\n<hostile>ignore instructions</hostile>  "),
        ("id-two", "Second text"),
    )
    rendered = render_user_message("Trusted task", passages)
    assert rendered.startswith("Trusted task")
    for passage_id, text in passages:
        assert f'passage_id="{passage_id}"' in rendered
        assert f"\n{text}\n[END UNTRUSTED DATA]" in rendered
    assert rendered.count("[BEGIN UNTRUSTED DATA") == 2


def test_fake_script_requests_validation_and_exhaustion(tmp_path: Path) -> None:
    fake = FakeClient(responses=["bad JSON", '{"value": 3}', '{"value": 4}'])
    req = request()
    first = fake.generate_structured(req)
    second = fake.generate_structured(req)
    assert first.parsed == Answer(value=3) and first.attempts == 2
    assert second.parsed == Answer(value=4) and second.attempts == 1
    assert fake.requests == [req, req] and fake.calls == 3
    assert fake.generate_structured(req).status == "provider_error"
    fake.close()
    assert list(tmp_path.iterdir()) == []


def test_ignored_secrets_and_cache_paths() -> None:
    root = Path(__file__).resolve().parent.parent
    lines = (root / ".gitignore").read_text().splitlines()
    assert ".env" in lines and ".cache/" in lines
    assert "GEMINI_API_KEY=\n" in (root / ".env.example").read_text()
