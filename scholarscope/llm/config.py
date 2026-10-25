"""Pydantic-validated environment settings; secrets excluded from dumps and repr."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from scholarscope.llm.base import LLMClient
from scholarscope.llm.cache import CacheMode, FileCache
from scholarscope.llm.fake import FakeClient
from scholarscope.llm.gemini import GeminiClient
from scholarscope.llm.groq import GroqClient
from scholarscope.llm.ollama import OllamaClient, validate_base_url


class LLMConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, allow_inf_nan=False, frozen=True
    )
    provider: Literal["gemini", "groq", "ollama", "fake"] = "fake"
    model: str = Field(default="fake-v1", min_length=1)
    gemini_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    groq_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    ollama_base_url: str = "http://localhost:11434"
    timeout_seconds: float = Field(default=30.0, gt=0)
    cache_mode: CacheMode = "read_write"

    @field_validator("ollama_base_url")
    @classmethod
    def checked_base_url(cls, value: str) -> str:
        return validate_base_url(value)

    @classmethod
    def from_env(cls) -> Self:
        # No dotenv or SDK needed: read this explicit allowlist, never dump os.environ.
        names = {
            "LLM_PROVIDER": "provider",
            "LLM_MODEL": "model",
            "GEMINI_API_KEY": "gemini_api_key",
            "GROQ_API_KEY": "groq_api_key",
            "OLLAMA_BASE_URL": "ollama_base_url",
            "LLM_TIMEOUT_SECONDS": "timeout_seconds",
            "LLM_CACHE_MODE": "cache_mode",
        }
        return cls.model_validate(
            {field: os.environ[env] for env, field in names.items() if env in os.environ}
        )


def build_client(
    config: LLMConfig, *, cache_dir: Path = Path(".cache/llm"), **kwargs: Any
) -> LLMClient:
    common = {
        "cache": FileCache(cache_dir, mode=config.cache_mode),
        "timeout_seconds": config.timeout_seconds,
        **kwargs,
    }
    if config.provider == "gemini":
        return GeminiClient(config.model, api_key=config.gemini_api_key, **common)
    if config.provider == "groq":
        return GroqClient(config.model, api_key=config.groq_api_key, **common)
    if config.provider == "ollama":
        return OllamaClient(config.model, base_url=config.ollama_base_url, **common)
    return FakeClient(config.model, **common)
