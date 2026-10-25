"""Deterministic scripted model output; no HTTP client, sleeping or randomness."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from scholarscope.llm.base import BaseClient, StructuredRequest, StructuredResponse, T, Usage


class FakeClient(BaseClient):
    provider = "fake"

    def __init__(
        self, model: str = "fake-v1", *, responses: Sequence[str] = (), **kwargs: Any
    ) -> None:
        super().__init__(model, **kwargs)
        self._responses = list(responses)
        self.requests: list[StructuredRequest[Any]] = []
        self.calls = 0

    def generate_structured(self, request: StructuredRequest[T]) -> StructuredResponse[T]:
        self.requests.append(request)
        return super().generate_structured(request)

    def _send(
        self, request: StructuredRequest[Any], user: str
    ) -> tuple[str | None, Usage, int, str | None]:
        if self.calls >= len(self._responses):
            return None, Usage(), 0, "fake response script exhausted"
        raw = self._responses[self.calls]
        self.calls += 1
        return raw, Usage(), 1, None
