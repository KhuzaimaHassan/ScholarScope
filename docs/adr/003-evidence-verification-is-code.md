# ADR 003 — Evidence verification is code, not an LLM

**Status:** Accepted · **Date:** 2026-10-12

## Context
The product promise is traceable facts. If an LLM both extracts a value and judges its own evidence, errors correlate and the check proves little. Two different questions must also be kept apart: does the quoted text exist in the cited passage, and does that text actually support the extracted value?

## Decision
- The **Evidence Verifier** is deterministic code. It checks that the quote exists in the cited passage (exact match, then normalized fuzzy match). It proves **presence** only.
- A field whose quote is not found becomes `unverified` (see ADR 008).
- Whether a verified quote **supports** its value is a **human-audited quality metric** on a sampled set of fields. An LLM judge may assist the audit but never replaces the human check.
- Evidence presence must be 100% for fields shown as `verified`; any miss is treated as a verifier bug.

## Consequences
- A "verified" field is a strong but not complete guarantee: a real quote can still be misread. The README and UI must not overclaim.
- The support metric costs human time but is the honest measure of extraction quality.
- Normalization rules (whitespace, quotes, hyphenation, PDF line breaks) need adversarial tests.

## Alternatives considered
- LLM self-verification: cheaper but correlated with the extractor's errors.
- Embedding-similarity checks: fuzzy and hard to explain; may be used as a diagnostic only.
