"""Private atomic file cache: response text/usage only, never prompts or headers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from scholarscope.llm.base import RENDERING_VERSION, StructuredRequest, Usage

CacheMode = Literal["read_write", "read_only", "off"]


class CacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    raw_text: str
    usage: Usage


def cache_key(provider: str, model: str, request: StructuredRequest[Any]) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "system": request.system,
        "task": request.task,
        "untrusted_passages": request.untrusted_passages,
        "response_schema": request.response_model.model_json_schema(),
        "temperature": float(request.temperature),
        "max_output_tokens": request.max_output_tokens,
        "prompt_version": request.prompt_version,
        "rendering_version": RENDERING_VERSION,
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FileCache:
    def __init__(
        self, directory: Path = Path(".cache/llm"), *, mode: CacheMode = "read_write"
    ) -> None:
        if mode not in {"read_write", "read_only", "off"}:
            raise ValueError("invalid cache mode")
        self.directory, self.mode = directory, mode

    def get(self, provider: str, model: str, request: StructuredRequest[Any]) -> CacheEntry | None:
        if self.mode == "off":
            return None
        path = self.directory / f"{cache_key(provider, model, request)}.json"
        try:
            return CacheEntry.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(
        self, provider: str, model: str, request: StructuredRequest[Any], raw: str, usage: Usage
    ) -> bool:
        if self.mode != "read_write":
            return True
        # Independent validation: even callers outside BaseClient cannot cache garbage.
        try:
            request.response_model.model_validate_json(raw)
            entry = CacheEntry(raw_text=raw, usage=usage)
        except (ValueError, TypeError):
            return False
        temporary: Path | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{cache_key(provider, model, request)}.json"
            with NamedTemporaryFile(dir=self.directory, prefix=".entry-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(entry.model_dump_json().encode("utf-8"))
            temporary.replace(target)
            return True
        except OSError:
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # A cache cleanup failure must not leak paths or model input.
