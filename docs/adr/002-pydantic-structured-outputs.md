# ADR 002 — Structured extraction via Pydantic schemas

**Status:** Accepted · **Date:** 2026-10-12

## Context
Extraction results feed deterministic code (eligibility, checklist), so free-form text is not acceptable. Every field must carry its evidence (quote and passage ID) and a status.

## Decision
Define the Requirement Record, Deadline, and ExtractedField as **Pydantic models**. The LLM must return output that validates against these schemas; invalid output is retried a bounded number of times, then the field is left empty.

Each extracted field is `{value, quote, passage_id, status, confidence}`, where `status` is `verified` or `unverified` and `confidence` is advisory only (see ADR 003 and 008).

## Consequences
- Typed, testable contracts between pipeline stages and a single source of truth for the database and API schemas.
- Schema changes are versioned together with prompt versions so evaluation results stay comparable.
- Models with weaker structured-output support need a validation-and-retry layer.

## Alternatives considered
- Free-text answers parsed with regexes: brittle and hard to test.
- Provider-specific function-calling formats only: ties the project to one vendor (see ADR 005).
