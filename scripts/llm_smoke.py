"""MANUAL ONLY: one tiny structured call; never prints keys, headers or model text."""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, ConfigDict

from scholarscope.llm import LLMConfig, StructuredRequest, build_client


class SmokeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str


def main() -> int:
    try:
        config = LLMConfig.from_env()
        client = build_client(config)
    except ValueError:
        print("Invalid LLM configuration (details withheld).")
        return 1
    started = perf_counter()
    try:
        result = client.generate_structured(
            StructuredRequest(
                system="Return the requested JSON.",
                task="Return a message containing hello.",
                untrusted_passages=(),
                response_model=SmokeResult,
                prompt_version="smoke-1",
            )
        )
        print(
            f"provider={result.provider} model={result.model} status={result.status} "
            f"usage={result.usage.model_dump()} latency_seconds={perf_counter() - started:.3f}"
        )
        return 0 if result.status == "ok" else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
