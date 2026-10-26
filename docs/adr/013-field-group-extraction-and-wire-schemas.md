# ADR 013 — Field-group extraction and provider wire schemas

**Status:** Accepted · **Date:** 2026-10-26

## Context

ADR 002 requires structured, locally validated extraction. The complete canonical
RequirementRecord schema includes keywords and complexity that providers may not
support. Removing constraints from that domain contract would weaken deterministic
validation. ADR 010 separates content status and verification; ADR 003/008/012
reserve quote-presence verification and retained failures for code.

## Decision

Amend ADR 002's provider-facing shape: one small Pydantic wire schema and one v1
prompt per identity, funding, documents, deadlines and conditions group. Use the
provider-neutral LLM interface (ADR 005), with temperature zero and provider-local
validation/retries. Test schemas with the Gemini unsupported-keyword guard;
never silently strip keywords from the canonical schema. Canonical schema.py and
older ADRs remain unchanged.

Convert successful wire output to full canonical domain models locally, enforcing
all constraints. Set every verification to not_checked, ignoring model claims.
Reject invalid items explicitly with raw input/reason/index and retain valid
siblings. Preserve failures in failed_groups and status/notes markers rather than
misrepresenting them as successful abstention. Empty placeholders are not evidence
that a page lacks a requirement; consumers must inspect extraction diagnostics.
Conditions remain implicitly present claims without a status property.

Page content appears only as untrusted passage pairs, never trusted prompts.
Group keyword retrieval is deterministic and keeps document order, the first
passage and HTML heading passages. These mandatory anchors may exceed the soft
character target; document truncation and per-group drops. This is not a hard
provider token bound or a guarantee of complete extraction.

The byte-to-record pipeline always runs the deterministic verifier after local
conversion, retaining a separate unchecked draft and verification report. No
extraction or model-supplied flag establishes presence or value support. Record
all processing/prompt versions and provider/model identity. See [doc 16](../16-extractor.md).

## Consequences

Five independent group calls isolate failures and allow smaller schemas without
weakening local contracts. More calls can cost more; provider-complexity failures
remain possible. Field-group selection can miss facts. Offline fictional tests
exercise contracts, never independent gold accuracy. Injection hardening (#21),
prompt registry (#22), real evaluations and hand-written labels remain separate.
