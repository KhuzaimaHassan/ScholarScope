# ADR 014 — Prompt-injection boundary defenses and residual risks

**Status:** Accepted · **Date:** 2026-10-27

## Context

ADR 013 keeps page content in untrusted passage tuples but its initial renderer
allowed delimiter-like text in passages. An LLM can emit schema-valid invented
links, fabricated citations or false claims. ADR 003/010/012 reserve verification
for deterministic quote-presence checks, not instruction compliance or truth.
The owner clarified issue #21's acceptance in a comment: enforce fencing, URL
provenance, schema integrity and verifier ownership; defer real-model compliance
measurement to M3 rather than claiming output invariance.

## Decision

Use one shared fenced JSON rendering for all adapters. Losslessly escape source
punctuation/control characters and Unicode inside string values so source text
cannot close fences, fake another passage record or create trusted sections.
Keep original segmented text/offsets untouched. Include RENDERING_VERSION (now 2)
in the cache key; bump it for any rendering behavior change.

After canonical conversion, reject application_link values and all field-level/
deadline-set linked_url metadata unless they occur verbatim in the selected
original passages for that group. Record URL_NOT_ON_PAGE with raw input and keep
valid siblings. Never fetch or repair. Literal provenance is not URL safety or
authority and does not make arbitrary output strings safe to render actively.

Run a deterministic, advisory regex scan over the segmented document; expose
passage IDs and reason codes in PipelineResult and the manual script summary.
Never filter/rewrite text or change output/verification based on the scan.
Keep the existing domain schemas, verifier and cleaner behavior unchanged.

Audit static hidden-text handling with synthetic sentinels. Inline display:none,
visibility:hidden, aria-hidden and comments are excluded. Tiny/zero-size and
stylesheet-only hiding reach passages; document this limitation explicitly.

## Consequences

Escaped data cannot forge request structure; software validation/verification
cannot be reassigned by model instructions. These are syntactic and local-code
guarantees, not a promise that a model follows trusted policy. A malicious URL
present on the page still passes provenance. An obeyed fake deadline with a real
quote can verify: the test documents a **residual risk, not a defended case**.
Presence alone never establishes support, correctness or authority.

Commit reusable fictional adversarial fixtures for the M3 harness's deferred
live-provider evaluation. No live inference, real page contents, labels or
snapshots are used here. See [threat model](../17-threat-model-injection.md) for
the owner-approved acceptance, hidden-text audit and residual-risk table.
