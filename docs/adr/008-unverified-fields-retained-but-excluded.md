# ADR 008 — Unverified fields are retained but excluded from logic

**Status:** Accepted · **Date:** 2026-10-12

## Context
Early drafts said evidence failures would be "dropped" in one place and "marked unverified" in another. Dropping hides useful leads from the user and from error analysis; using unverified values in decisions risks wrong verdicts and dates.

## Decision
When a field fails evidence verification (ADR 003) it is **retained and marked `unverified`**.

- It is shown in the UI with a clear "unverified: check official page" notice.
- It is **excluded from eligibility and checklist logic**: rules needing it return `unclear`, and unverified deadlines are never used to compute buffers or dates.
- It is kept in storage and in evaluation, so abstention quality and failure classes can be measured and analyzed.

## Consequences
- Users see everything the system found but cannot be misled into acting on unverified data automatically.
- The UI and API must carry the status through every layer, and tests must prove the exclusion.
- Evaluation tracks how often unverified fields were actually correct, which feeds error analysis.

## Alternatives considered
- Drop failed fields: simpler but hides information and removes data for error analysis.
- Use unverified fields with a warning: risks wrong verdicts and dates.
