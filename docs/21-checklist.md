# Evidence-gated checklist and calendar buffers

`scholarscope.checklist.build_checklist(record, now, policy=DEFAULT_POLICY, *,
reference_tz=UTC)` is pure: no clock, I/O, network, profiles, extraction or LLM
dependencies. Supply an aware `datetime`; a naive value raises `ValueError`.
`reference_tz` must be an explicit `tzinfo` (default UTC, never the machine zone).
Every comparison calls the existing `deadlines.compare(deadline, now)` with the
original instant unchanged. No deadline resolution/comparison rules are replaced.

Calendar **today = `now.astimezone(reference_tz).date()`**. Only buffer arithmetic
and the comparison of a planned date to today use this calendar. Never convert a
source's stated date into another timezone, infer a time/zone/year, or buffer by
hours. The result echoes `now`, the actual `reference_tz` object, `today` and the
policy so callers can reproduce a plan.

## Output and policy

`Checklist` and `ChecklistItem` are frozen dataclasses; items and warning codes
are tuples. Evidence objects are deep copies of source `Evidence`, including
quote, passage ID, locator and context. Evidence on dependent tasks includes both
the requirement field's quotes and the anchor deadline's quotes. Inputs are never
mutated. No claim is promoted to verified; verification still proves presence,
not that a value is supported or that a source is true.

`BufferPolicy` is frozen, strict Pydantic, with extra properties forbidden:

| Property | Default / meaning |
|---|---|
| `id`, `version` | `buffer-default`, `1` |
| `submit_buffer_days` | 7 calendar days before a stated, known-zone deadline |
| `recommendation_lead_days` | 21 calendar days before the raw submit deadline, not 21 days before the already buffered date |
| `rationale` | Seven days for submission preparation and three weeks for requesting letters are configurable working defaults, not measured guarantees |
| `source_note` | Always `project decision, not from any program` |

Day counts are nonnegative integers; zero is valid. Every item carries
`policy_id` and `policy_version`, even if undated. There is no inference that a
program itself requests these buffers. Callers should version their policy when
changing it. Policy settings are also included in the deterministic item hash.

Each item has `id`, `kind`, `title`, `due_date`, `warnings`, `source`, `evidence`,
`policy_id`, `policy_version`. `source` is a record field path, e.g. `deadlines[0]`
or `fields.required_documents.value[1]`. Titles show a deadline's stated label,
type, cycle, date, time and timezone when used (including explicit `None`/`unknown`,
without substitutes). IDs hash canonical JSON of source URL, path, kind, policy
and anchor deadline identity. Repeated entries have distinct indexed paths.
IDs are stable for the same record/policy and action kind, independent of the
clock input, confidence, or mutable quote copies. Reordering source entries,
changing anchor/policy/kind can change IDs; they are not global program IDs.

Sort by due date, then explicit kind order, then ID; undated items are last. The
kind order is `submit_application`, `request_recommendations`, `prepare_document`,
`deadline`, `check_official_page`, `closed`, `apply_early`. Warnings are unique and
sorted by code. This order is explicit, not dependent on dictionary iteration.

## Rules and precedence

| Priority | Situation | Result |
|---|---|---|
| 1 | Whole deadline set absent/linked, or no entries | One undated `check_official_page`; no deadlines inferred |
| 2 | Ambiguous set/entry, or deadline not `usable_for_logic` | Undated `check_official_page` per entry, retaining evidence; no date calculation. Ambiguous empty sets get one whole-set check. |
| 3 | Usable rolling entry | One `apply_early`, no date or buffer, `ROLLING` |
| 4 | Usable fixed deadline; `compare()` says past | `closed`, no due date, `DEADLINE_PASSED`; no future reminder for that cycle |
| 5 | `compare()` upcoming/unknown, but reference-calendar today is after the stated date | `check_official_page`, no due date, `REFERENCE_DATE_AFTER_DEADLINE`; show raw date/time/timezone and retain deadline evidence. Applies to all dependent items as well. |
| 6 | `compare()` unknown within the global date-only closing window | `check_official_page`, no due date, `DATE_ONLY_WINDOW`; show the stated date. This warning also accompanies priority 5 when comparison is unknown. |
| 7 | Upcoming fixed deadline without a known source zone | `deadline` with its stated date, unbuffered, `TIMEZONE_UNKNOWN`; also `TIME_UNKNOWN` when no time is stated |
| 8 | Upcoming fixed deadline with known zone | `submit_application` preparation item, stated date minus submission buffer, using calendar dates only |
| 9 | A computed buffer date is before today, and priorities 4–6 did not block it | Clamp to today, `BUFFER_ALREADY_PASSED`; equality with today needs no clamp warning |

The submission/preparation path is applied independently to each fixed deadline;
its original type/label remain visible (including document, recommender,
interview and other deadlines). The checklist neither executes an application
nor schedules an event. Multiple cycles stay separate. Closed cycles cannot
become anchors for future preparation tasks.

For recommendations/documents, the anchor is the earliest stated calendar date
among usable, non-rolling, non-past `application`/`scholarship` deadlines, with
source index breaking ties. An earlier uncertain/cross-calendar anchor is not
silently replaced by a later easy-to-resolve cycle. Other deadline types never
invent a submission anchor.

- **Recommendations:** present and verified only; subtract the recommendation
  lead from the anchor's raw date, subject to the same comparison/reference-date
  guards and clamp. Unknown zone yields no derived date. Explicit maximum zero
  produces no request. Non-absent but unusable fields produce an official-page
  check. Missing fixed anchor produces an undated request, not an inferred date.
- **Documents:** one preparation item per entry of a present, verified document
  field, with the anchor's planned submission date (or its unbuffered date).
  There is no independent document buffer or profile matching. The same guards
  turn unsafe derived items into official-page checks. Missing anchor means no
  date. A non-absent unusable field produces one official-page check.
- Absent recommendation/document fields create no invented requirements. An
  unusable whole deadline set cannot supply dates, even if a structurally allowed
  record contains apparently verified child entries. Confidence is never read.

### Cross-calendar exception and invariant

Deadline 2 November 2026 23:59 UTC is still upcoming at 23:30 UTC. In reference
timezone UTC+05:00, however, today is already 3 November. Clamping a missed buffer
to today would place the action **after the source's stated date**. Emit an
undated official-page check instead, with `REFERENCE_DATE_AFTER_DEADLINE` and
the original deadline details/evidence. The same applies to unknown-zone raw
dates when comparison is upcoming/unknown. A reference timezone behind UTC can
retain the previous date safely; compare still uses the unchanged instant.

**Invariant:** no emitted due date exceeds its anchor's stated deadline date.
The exception applies before all clamping and date display/derivation, including
recommendation leads and document preparation. Comparison-past entries remain
closed; no calendar exception makes a closed entry upcoming.

### Unknown zones: existing contract unchanged

The schema represents an unstated zone as `None` for date-only data or `"unknown"`
when the source gives a time but no zone. Both are unknown, never known zones.
This follows **issue #40's acceptance criterion and docs/02 line 56 unchanged**:
warn, no buffer. The global window remains doc 11's: upcoming before D 10:00 UTC,
past at/after (D+1) 12:00 UTC, unknown between those instants. These bounds are
not assumed closing times for a source.

Known cost: many pages will not state a timezone, so checklists will show
unbuffered dates (or undated checks in uncertain windows) until real extractor
output establishes how common this is. Amend this policy only with evidence
from real outputs and an explicit reviewed decision, not a guessed source zone.

## Warning glossary

| Code | Meaning |
|---|---|
| `TIMEZONE_UNKNOWN` | No known source zone; no buffered date (None or literal unknown) |
| `TIME_UNKNOWN` | No stated time; no time invented |
| `DATE_ONLY_WINDOW` | Existing global comparison cannot safely decide whether the deadline is past/upcoming |
| `DEADLINE_PASSED` | Existing comparison says past; closed item has no due date |
| `UNVERIFIED_SOURCE` | Content status or verification makes the source unusable for planning |
| `ROLLING` | No fixed date; apply early without a dated buffer |
| `BUFFER_ALREADY_PASSED` | Proposed calendar date was before today; safely clamped to today |
| `REFERENCE_DATE_AFTER_DEADLINE` | Reference calendar is beyond the stated date while comparison is upcoming/unknown; never clamp/show a due date |
| `DEADLINE_UNAVAILABLE` | No usable non-past fixed submit anchor; no derived date |
| `BUFFER_OUT_OF_RANGE` | Configured calendar subtraction exceeds the representable date range; check, do not invent a date |
| `DST_GAP` | Resolver used its documented fold=0 interpretation for a nonexistent local time |
| `DST_OVERLAP` | Resolver used fold=0 for an ambiguous local time |

## Not implemented

Missing-document matching (#41), profile use, eligibility verdicts, time-of-day
buffers, reminders/notifications, storage, or live source/LLM calls. A verified
quote's presence is not evidence-support judgment. No labels or snapshots are
read or written by this module. Tests use fictional records, a socket guard and
a seeded 600-case calendar-safety loop; no new dependencies are required.

See [ADR 019](adr/019-checklist-buffers-and-unknown-timezones.md).
