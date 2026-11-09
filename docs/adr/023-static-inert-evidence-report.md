# ADR 023 — Static, inert evidence report as the first UI slice

**Status:** Accepted · **Date:** 2026-11-09

## Context

Pipeline, verification and checklist results need a human-readable local view
before the planned API and Next.js product. A report must distinguish quote
presence from support, expose extraction failures and remain safe when source
text or model output contains hostile markup. ADR 020 permits guarded provider
messages only in memory and console, never persisted reports.

## Decision

Use a pure `render_report` function with standard-library string construction
and `html.escape`, explicit `now` and reference timezone. Add an optional
immutable segmented document to PipelineResult so the renderer uses existing
passages and verifier offsets, including cross-passage and synthetic-target
spans. Keep verifier, guards, checklist policy and extraction prompts unchanged.

Emit standalone HTML with one static style block, no scripts or remote
resources, and CSP `default-src 'none'; style-src 'unsafe-inline'`. Escape all
dynamic strings, display format controls visibly, and limit displayed entries
and passages to 2,000 original characters with a truncation label. Only an
explicitly supplied and validated HTTP(S) source URL becomes an external link,
with noopener/noreferrer/nofollow; evidence uses generated internal anchors.
All page-derived URLs stay plain text.

Allowlist diagnostics: group status and failure category, rejection
group/index/reason, and truncation counters. Never render provider messages,
raw responses, raw rejected items or free-form pipeline errors. Failed groups
have a distinct badge. Include existing verified-only checklist output,
warning codes, evidence and policy provenance. Quote-presence labels and a
visible footnote explain that presence does not prove support.

The local-snapshot CLI forces read-only caching unless `--live` is explicit;
cache misses display failures without sending. Restrict output to resolved
paths under ignored eval/reports, or explicit docs/examples output, refusing
protected and redirected destinations. Commit only a conspicuously synthetic,
scripted FakeClient sample, reproducible with a flag and checked for drift.
No new dependencies.

## Consequences

This is the first static UI slice, with no server, editing, profile eligibility,
hosted storage or accuracy claims. Real reports contain private source text and
must remain private. Truncation can hide a highlighted span; original offsets
remain unchanged. Injection findings remain advisory. Offline tests prove
escaping, offsets, cache-only behavior and deterministic presentation, not
semantic support or model compliance. The API and Next.js roadmap remains
planned; this view does not replace those requirements.
