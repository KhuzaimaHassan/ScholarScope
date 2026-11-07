# ADR 021 — Numeric provenance guard

**Status:** Accepted · **Date:** 2026-11-07

## Context

Quote-presence verification does not establish that a model's numeric value
occurs in its quote. Valid wire output can associate a fabricated score, GPA
scale or funding amount with an otherwise genuine quote. The owner requested a
numeric control analogous to URL provenance and explicitly resolved check-order
precedence in favor of provenance diagnostics.

## Decision

After wire parsing, check each item in order: (1) numeric provenance, (2) URL
provenance, (3) canonical domain validation. First failure wins; never merge
reasons, repair numbers, invent values or promote verification. This amends the
earlier post-domain URL-check order in ADR 014. Deadline-set metadata retains its
URL check before its set-level domain checks.

Guard GPA value and scale, each language-option min_overall and min_subscore,
and funding-entry amount and amount_max. Only the item's own evidence quotes
qualify; funding entries share the field-level evidence list. Null optional
values need no match; malformed nonnumeric shapes reach domain validation.
Reject a failing condition or funding entry as NUMBER_NOT_IN_QUOTE:<field> with
its original index/raw item; retain valid siblings. Rejected raw values stay only
in raw_item, never repaired into record values/notes. If every funding entry is
rejected, mark the funding group failed rather than successful absence.

Extract tokens with `\d[\d.,]*`, strip trailing punctuation, and parse both comma
interpretations: thousands separator (remove commas) or decimal point (remove
period grouping and replace commas). Without commas, retain decimal periods.
Use exact finite-float equality, without tolerance or substring matching.
Currency suffix punctuation contributes no additional digit. Ambiguous numeric
interpretations are deliberately retained, not resolved from context.

Canonical LanguageOption requires min_overall > 0 and optional min_subscore > 0.
This narrowly tightens the domain schemas preserved by ADR 013/014; provider
wire models and the structural gold JSON schema remain unchanged. Missing zero
fails numeric provenance; quoted zero fails the domain backstop with its existing
reason format. No labels/snapshots are modified; the fictional gold example must
pass both the existing validator and canonical conversion.

## Consequences

Numbers in a quote can still have the wrong semantic role, currency or unit.
This is presence-only, never support, authority or accuracy proof; the unchanged
quote verifier still runs. Number words/spelled-out decimals are unsupported
(and may cause false rejections for guarded values). Recommender counts, dates,
times and age conditions are known unguarded gaps. Locale ambiguity and unrelated
numbers in the same quote can cause acceptance.

Identity-v2, funding-v3 and conditions-v3 address general policy ambiguities;
each changed task/version invalidates cache identity. Offline tests can assert
instructions and software contracts, but prompt effects require manual real
runs. Use fictional fixtures and mocked/scripted providers here; no live calls,
accuracy claims or new dependencies.
