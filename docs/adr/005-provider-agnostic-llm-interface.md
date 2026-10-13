# ADR 005 — Provider-agnostic LLM interface

**Status:** Accepted · **Date:** 2026-10-12

## Context
The project targets free LLM tiers (for example Gemini and Groq) with a local fallback (Ollama). Free-tier limits, model deprecations, and rate limits change often, and contributors may use different providers.

## Decision
Put all model calls behind one small **LLM interface** (structured-output request in, validated Pydantic object out). Provider choice, model name, and retry/backoff settings come from configuration. Responses are cached by `(content_hash, prompt_version, model)`.

Every stored extraction records the model and prompt version used.

## Consequences
- Swapping providers is a config change, and evaluation runs can compare providers fairly.
- The interface must stay minimal; provider-specific features are used only inside adapters.
- Cached responses make evaluation runs cheap and reproducible, but the cache key must change whenever the prompt or schema changes.

## Alternatives considered
- Binding directly to one vendor SDK: fastest start, but fragile on free tiers.
- A large third-party abstraction layer: more features than needed and another dependency to track.
