# ADR 010 — Two-axis field status and evidence verification

**Status:** Accepted · **Date:** 2026-10-20

## Context

ADR 002's single `verified`/`unverified` status conflated what the page says with whether code found its evidence. Gold labels distinguish present, absent, ambiguous, and linked information. A claim can be present without having been checked; a failed check must not erase its value or quote. Renaming `present` to `verified` would incorrectly imply a deterministic check occurred.

## Decision

- `status` is `present`, `absent`, `ambiguous`, or `in_linked_document`, matching hand labels.
- `verification` is `not_checked` (default), `verified`, or `unverified`. Only the deterministic verifier (#20) sets the latter two. The model validates states; it does not prove who supplied them. Extractor orchestration must keep verification at `not_checked` until that verifier runs.
- Each generic field contains `value`, an `evidence` list, `linked_url`, `notes`, and advisory `confidence`. Each evidence item has a 1–400 character quote, nullable passage ID and locator; optional gold disambiguation context is preserved. No offsets are added yet.
- Present claims require non-empty values and evidence. Ambiguous claims require null values and evidence. Absent and linked claims require null values, no evidence, and `not_checked`; linked claims also require a link. Verified/unverified states require evidence to check.
- Failed verification keeps the claim's value and failed quote; it never silently drops them.
- `usable_for_logic` is true **only** for `status="present"` and `verification="verified"`. This encodes ADR 008's exclusion policy. Confidence never affects this property or any eligibility/checklist decision.
- Gold conversion always initializes verification to `not_checked`; a human label is not a deterministic-verifier result.

## Consequences

Extractor output and hand labels share field names and value shapes without confusing presence with verification. The schema exposes separate axes; downstream engines must use the usability policy, not content status or confidence alone. This amends ADR 002's field-model description; its historical text remains intact. Deadline policy (#17), extractor calls (#19), and evidence checking/state transitions (#20) remain separate work.
