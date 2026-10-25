"""Local Ollama /api/chat wire format; official docs checked 2026-10-25."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from scholarscope.llm.base import BaseClient, StructuredRequest, Usage, token_count


def validate_base_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        raise ValueError("OLLAMA_BASE_URL has an invalid host or port") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OLLAMA_BASE_URL must be HTTP(S), without credentials, query or fragment")
    return url.rstrip("/")


class OllamaClient(BaseClient):
    provider = "ollama"

    def __init__(
        self, model: str, *, base_url: str = "http://localhost:11434", **kwargs: Any
    ) -> None:
        super().__init__(model, **kwargs)
        self.base_url = validate_base_url(base_url)

    def _endpoint(self) -> str:
        return self.base_url + "/api/chat"

    def _payload(self, request: StructuredRequest[Any], user: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": user},
            ],
            "format": request.response_model.model_json_schema(),
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }

    def _extract(self, data: dict[str, Any]) -> tuple[str | None, Usage]:
        raw = data.get("message", {}).get("content")
        return raw if isinstance(raw, str) else None, Usage(
            input_tokens=token_count(data.get("prompt_eval_count")),
            output_tokens=token_count(data.get("eval_count")),
        )
