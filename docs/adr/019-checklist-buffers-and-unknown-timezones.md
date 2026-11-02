# ADR 019 — Checklist buffers and unknown source timezones

**Status:** Accepted · **Date:** 2026-11-02

## Context

Checklist dates must be reproducible, traceable to verified claims and explicit
about project planning policy. The deadline resolver/comparator already handles
stated instants and the global unknown-zone closing window. A caller's calendar
can be a day ahead of a still-open source deadline, making an otherwise reasonable
clamp to today unsafe relative to the source's printed date.

## Decision

- Use `build_checklist(record, now, policy=DEFAULT_POLICY, *, reference_tz=UTC)`.
  Require aware `now`; pass it unchanged to `deadlines.compare`. Echo it, the
  reference timezone, `today = now.astimezone(reference_tz).date()` and policy.
  No clock, I/O, profile, extraction or provider dependency. Confidence is unused.
- Use frozen dataclasses for checklist/items and frozen strict Pydantic for
  `BufferPolicy`. Default policy `buffer-default` version `1` uses seven calendar
  days for submission/preparation and twenty-one for recommendation requests
  before the raw deadline. These are configurable working defaults, explicitly
  `project decision, not from any program`, never claimed as program requirements.
- Gate dates on `usable_for_logic` (ADR 010). Absent/linked sets and ambiguous
  or unverified claims become undated official-page checks. Rolling claims get
  apply-early items without dates; past fixed deadlines get closed items.
- Follow **issue #40 and docs/02 line 56 unchanged**: unknown source timezone
  means warn, no buffer. Both None and the model's literal `unknown` count as
  unknown. Show only the stated, unbuffered date when comparison is upcoming;
  if comparison is unknown, use an undated check with `DATE_ONLY_WINDOW`.
- Known-zone buffers use date arithmetic, not hours. Clamp a missed proposed
  buffer to reference-calendar today only if it does not exceed the stated date.
- **Approved cross-calendar exception:** when comparison is upcoming/unknown
  and reference-calendar today exceeds the stated deadline date, emit an undated
  `check_official_page` with `REFERENCE_DATE_AFTER_DEADLINE`, deadline evidence
  and raw date/time/timezone in the title. Apply before all date derivation or
  display, including recommendation leads, document dates and unknown-zone
  deadline items. Never emit a buffered or deadline-kind date in this case.
- Dependent tasks use the earliest usable non-past fixed application/scholarship
  calendar date, with source index breaking ties. Keep uncertainty on that anchor
  visible; do not skip it for a later cycle. Recommendations require a usable
  recommendation field and get no derived date for unknown zones; explicit zero
  maximum creates no request. Documents require a usable field and inherit the
  anchor's planned submission/unbuffered date, without matching profile holdings.
- Preserve resolver DST warnings and source evidence as deep copies. Every item
  records policy ID/version, deterministic content-based ID and source field path.
  Order by date, explicit kind order and ID, with undated items last.

## Consequences

No emitted due date exceeds its source anchor's stated date, even across caller
timezones. For example, 2 November 23:30 UTC is before a 2 November 23:59 UTC
deadline, but UTC+05:00's today is 3 November: generate an official-page check,
not a clamped 3 November date. The mirror calendar-behind case can safely retain
2 November. The instant comparison itself never changes or guesses a zone.

Many sources may omit timezones. Plans will consequently contain unbuffered
dates or undated checks; real extractor output must establish how common this is
before any future amendment. Evidence, then an explicit reviewed decision, is
required to relax the policy. Defaults are not guarantees, source verification
is quote presence only, and no missing fact or deadline is invented.

No missing-document matcher, profile integration, time-of-day buffering,
reminders/notifications, storage or real source/LLM calls are implemented.
See [the checklist contract](../21-checklist.md) for precedence and warnings.
