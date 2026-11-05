# ADR 020 — Ephemeral, guarded provider failure details

**Status:** Accepted · **Date:** 2026-11-06

## Context

The original [LLM contract](../15-llm-interface.md) allowed only fixed error text
and status codes. A failed field group consequently could not distinguish a
provider quota failure from invalid/over-complex response schemas. The owner
authorized a narrow exception for diagnosing these failures, with no relaxation
of the request/page-text or credential boundary.

## Decision

Keep `StructuredResponse.error` fixed. Add ephemeral `failure_detail`, carried
into `ExtractionResult.failure_details` per failed group: a category, nullable
HTTP status, and an optional message. Categories are rate_limited, server_error,
bad_request, timeout, schema_rejected and other. Schema rejection is terminal;
never strip schemas or downgrade a rejected request. Retain existing retry limits
for transient HTTP/transport failures.

Only HTTP 4xx/5xx or provider-reported structured errors can supply a message.
Take only the structured `error.message` string; if missing, use null. Redact
known credentials, key/token-shaped strings and URL queries first. Then discard
the whole message if any 20-character window of request system/task/passages or
their sent text occurs in it, using `[withheld: matched request text]`. Collapse
whitespace and truncate to 300 characters last. Never use request bodies, page
text, credentials, query-bearing URLs, raw response bodies, exception strings
or stack traces as diagnostics.

The sanitized message is available only in memory and the manual extractor's
console output, excluded from repr. Never store it in LLM cache files, snapshots,
reports, logs or Requirement Records. Record notes retain only existing
`EXTRACTION_FAILED:<group>:<status>` markers. Persistent report builders continue
using explicit allowlists that exclude these messages. Users must not redirect
or save the diagnostic console output.

Measure each group call with a wall-clock performance timer; expose statuses,
latency and returned token usage separately from the record. Cache hits may have
historic token counts; usage is not retry-cost accounting. Use fictional fixtures,
FakeClient and mocked transport tests only, including persistence-boundary tests.

## Consequences

Diagnostics distinguish operational/schema failures without claiming accuracy
or retaining raw responses. Redaction is conservative and may hide useful detail;
the echo guard is literal and cannot detect paraphrases or shorter echoes.
Messages remain untrusted, inert text. No new dependency, schema migration,
snapshot rewrite, live model run or change in evidence-verification policy.
