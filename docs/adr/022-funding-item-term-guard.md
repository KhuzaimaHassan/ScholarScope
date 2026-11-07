# ADR 022 — Funding item-term guard

**Status:** Accepted · **Date:** 2026-11-07

## Context

An item category can be unsupported even when a field's numeric values and
quotes pass presence controls. The owner requested an English category-term
control for funding entries without changing the canonical vocabulary or making
semantic-support claims. [Doc 16](../16-extractor.md) lists the complete lexicon.

## Decision

Use the documented FUNDING_ITEM_TERMS constant in extraction/guards.py, with a
nonempty list for every non-other FundingCoverage.item Literal value. Terms are
English only; residence, stay, permit and grant are excluded. Other bypasses the
term guard only. Match `\b` plus the literal escaped term, case-insensitively, on
the original quote text: word-start matching allows suffixes but not interior
substrings. Do not normalize whitespace, translate, fuzzy-match or join quotes.
All evidence quotes of funding_coverage qualify because evidence is field-level.

Funding entry check order is numeric provenance, item-term provenance, then
canonical domain validation; first failure wins, without combined reasons or
repaired values. This extends ADR 021 for funding categories. Entries have no URL
properties; the enclosing field's linked_url retains its existing URL guard
before field domain validation. Other item types retain ADR 021's check order.

A failed entry is rejected as ITEM_TERM_NOT_IN_QUOTE:<item>, retaining the
original index/raw item and valid siblings. Never reclassify it as other. If all
entries fail, conversion leaves the field absent with EXTRACTION_REJECTED; group
orchestration preserves this note alongside its mandatory EXTRACTION_FAILED
marker and reports failed, not successful absence. Preserve numeric-rejection
notes in the same way. Raw items remain subject to existing private/opt-in output
rules; do not log them implicitly or copy them into record values/notes.

Add funding-v4 instructions to select only quote-named categories, use other for
unlisted kinds, and choose the shortest quote wording naming each cost for notes.
Version/task changes invalidate cache identity; historical prompts remain in the
leak test. No schema, verifier, source-cleaning or dependency changes.

## Consequences

This guards item categories only, not semantic support, actual funding, truth,
currency/amount/period association or note quality. A category word anywhere in
shared field quotes can pass; irrelevant prefixes or negations can also pass.
Non-English quotes without matching English terms cause explicit reported
rejections for non-other entries, not silent drops or translation; English
loanwords may match. Other is not an inference or an automatic repair path.
The unchanged quote verifier still runs independently. Offline fictional tests
verify code contracts and prompt/cache versions, not real-model compliance;
prompt effects need manual real runs. No live calls or accuracy claims here.
