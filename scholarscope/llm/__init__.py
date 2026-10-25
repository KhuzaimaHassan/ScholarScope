"""Typed generation only; extraction and injection hardening remain #19 and #21."""

from scholarscope.llm.base import (
    LLMClient,
    StructuredRequest,
    StructuredResponse,
    Usage,
    render_user_message,
)
from scholarscope.llm.config import LLMConfig, build_client
from scholarscope.llm.fake import FakeClient

__all__ = [
    "FakeClient",
    "LLMClient",
    "LLMConfig",
    "StructuredRequest",
    "StructuredResponse",
    "Usage",
    "build_client",
    "render_user_message",
]
