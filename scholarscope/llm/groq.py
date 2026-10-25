"""Groq Chat Completions formats; model support checked in official docs 2026-10-25."""

from __future__ import annotations

import json
from typing import Any

from scholarscope.llm.base import BaseClient, StructuredRequest, Usage, schema_nodes, token_count

STRICT_MODELS = frozenset(
    {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "meta-models/muse-spark-open"}
)
SCHEMA_MODELS = STRICT_MODELS | {"openai/gpt-oss-safeguard-20b"}


def strict_compatible(schema: dict[str, Any]) -> bool:
    return all(
        node.get("additionalProperties") is False
        and set(node.get("required", [])) == set(node.get("properties", {}))
        for node in schema_nodes(schema)
        if node.get("type") == "object" or "properties" in node
    )


class GroqClient(BaseClient):
    provider = "groq"

    def _endpoint(self) -> str:
        return "https://api.groq.com/openai/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key.get_secret_value() if self._key else ''}"}

    def _payload(self, request: StructuredRequest[Any], user: str) -> dict[str, Any]:
        schema = request.response_model.model_json_schema()
        if self.model in SCHEMA_MODELS:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": self.model in STRICT_MODELS and strict_compatible(schema),
                    "schema": schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
            user += "\n\nResponse JSON Schema:\n" + json.dumps(
                schema, sort_keys=True, ensure_ascii=False
            )
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": user},
            ],
            "response_format": response_format,
            "temperature": request.temperature,
            "max_completion_tokens": request.max_output_tokens,
            "stream": False,
        }

    def _extract(self, data: dict[str, Any]) -> tuple[str | None, Usage]:
        usage = data.get("usage") or {}
        raw = data.get("choices", [{}])[0].get("message", {}).get("content")
        return raw if isinstance(raw, str) else None, Usage(
            input_tokens=token_count(usage.get("prompt_tokens")),
            output_tokens=token_count(usage.get("completion_tokens")),
        )
