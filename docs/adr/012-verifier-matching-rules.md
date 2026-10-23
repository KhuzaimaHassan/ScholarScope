# ADR 012 — Formatting-only evidence matching and original offsets

**Status:** Accepted · **Date:** 2026-10-23

## Context

ADR 003's “normalized fuzzy” means tolerance for formatting, not changed facts.
Digit/word edits can make almost identical quotes dangerously wrong. ADR 008/010
require retained failures and verifier-owned state; ADR 011 supplies immutable,
contiguous passage offsets rather than copied or interpreted source text.

## Decision

Use a pure deterministic verifier (`VERIFIER_VERSION="1"`) that returns a deep
independent Requirement Record and a per-quote report. Recompute all Field,
Deadline and evidence-bearing Condition verification, ignoring incoming states.
Every quote must pass; never drop values or rewrite citations. Conditions gain
verifier state, defaulting to not_checked, and gold conversion resets it.

Apply outcome precedence: invalid quote; missing/unknown citation; exact;
normalized; contiguous match starting/ending in the cited passage and spanning
adjacent passages; found elsewhere (suggestion only); not found. Reject quotes
below six normalized characters/two Unicode word-number tokens and ellipses.

Allow NFKC, curly quotes/apostrophes and en/em dash to ASCII, whitespace collapse,
soft-hyphen/zero-width removal, and literal hyphen + LF/CRLF joining only. No case,
digit/letter or homoglyph folding, no edits, no stitched fragments. Track origins
through normalization; validate original slices before reporting half-open
document offsets. Count duplicate locations; context may disambiguate but never
manufactures presence. Report every touched passage and document-ordered
suggestions, with deterministic outcome totals. No optional near-match diagnostic
is implemented. Full rules are in [doc 13](../13-verifier.md).

## Consequences

Verified means **presence only**, not support, correctness, freshness, or legal
authority. Human support audits remain necessary. Confidence cannot affect any
check. Failed claims and evidence remain visible but unusable for logic. Source
maps, gold labels and snapshots are untouched. Independent normalization/original
offset tests guard the 100% presence invariant; formatting rules may intentionally
produce false negatives rather than accepting changed digits or words.
