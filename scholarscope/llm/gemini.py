"""Gemini generateContent REST wire format; checked against official docs 2026-10-25."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from scholarscope.llm.base import BaseClient, StructuredRequest, Usage, schema_nodes, token_count

# GenerationConfig JSON-Schema supported-keyword list. Reject, NEVER strip.
SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$id",
        "$defs",
        "$ref",
        "$anchor",
        "type",
        "format",
        "title",
        "description",
        "enum",
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "anyOf",
        "oneOf",
        "properties",
        "additionalProperties",
        "required",
        "propertyOrdering",
    }
)


def unsupported_keywords(schema: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                key
                for node in schema_nodes(schema)
                for key in node
                if key not in SUPPORTED_SCHEMA_KEYWORDS
            }
        )
    )


class GeminiClient(BaseClient):
    provider = "gemini"

    def _capability_error(self, request: StructuredRequest[Any]) -> str | None:
        error = super()._capability_error(request)
        if error:
            return error
        if unsupported_keywords(request.response_model.model_json_schema()):
            return "Gemini schema contains unsupported keywords; use a compatible response model"
        return None

    def _endpoint(self) -> str:
        model = self.model.removeprefix("models/")
        return f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._key.get_secret_value() if self._key else ""}

    def _payload(self, request: StructuredRequest[Any], user: str) -> dict[str, Any]:
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": request.response_model.model_json_schema(),
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }

    def _extract(self, data: dict[str, Any]) -> tuple[str | None, Usage]:
        usage = data.get("usageMetadata") or {}
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        texts = [
            p["text"]
            for p in parts
            if isinstance(p, dict)
            and isinstance(p.get("text"), str)
            and not p.get("thought", False)
        ]
        return ("".join(texts) if texts else None), Usage(
            input_tokens=token_count(usage.get("promptTokenCount")),
            output_tokens=token_count(usage.get("candidatesTokenCount")),
        )
