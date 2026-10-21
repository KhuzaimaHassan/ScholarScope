# Deadline validation, resolution and ordering

The existing `scholarscope.schema.Deadline` is extended, not replaced. Gold fields remain label/type/cycle_year/date/time/timezone/rolling/status/evidence/notes. Extractor-only `verification` defaults to `not_checked`. Quotes and values are not rewritten, and no source timezone, time, or year is inferred. `tzdata` is a declared dependency and installed by CI so `zoneinfo` works on Windows without an OS timezone database.

## Validation and gold parity

- Present and ambiguous deadlines need at least one 1–400 character evidence quote.
- Rolling deadlines have no date. Present non-rolling deadlines require a date; ambiguous deadlines have no selected date and retain the conflicting quotes/candidates in evidence/notes.
- Time requires timezone and timezone requires time. Use `unknown` only when the source gives a time but no zone; do not derive a zone from an institution/country.
- Time is 24-hour HH:MM; dates are real ISO calendar dates. The cycle year is retained independently, even if different from the date's year.
- The single exported `schema.TZ_PATTERN` checks timezone syntax, and `timezone_info` checks semantics. Allowed: `unknown`, `UTC`, numeric `UTC+hh:mm`/`UTC-hh:mm` offsets strictly inside 24 hours (00–23 hours, 00–59 minutes), and names actually known to `zoneinfo`, including aliases such as `CET` and `Etc/GMT+5`. A syntactically plausible but unknown IANA name is rejected. Numeric offsets describe stated fixed offsets, not assumed political zones.
- A Requirement Record rejects duplicate keys `(type, cycle_year, date, time, timezone, label)`; it preserves distinct cycles/types and source order. Distinct evidence or notes do not make an identical key non-duplicate. Represent one conflicting deadline as one ambiguous entry with both quotes, not two identical null-date entries.

The approved first commit fixes a gold-validator bug: `check_deadline` previously passed dummy value `"x"` through the generic field helper, which rejects non-null values for ambiguous fields. Deadlines have no value member. They now have their own evidence check; the first commit changes no other rules/messages. A subsequent deadline-model commit imports the shared timezone pattern/helper so timezone recognition cannot drift. Tests reuse the same copied fictional ambiguous case and existing negative deadline mutations across both validators. The committed fictional example and actual labels are untouched.

## Neutral resolution

`scholarscope.deadlines.resolve(deadline) -> ResolvedDeadline` returns `instant_utc` (aware datetime or null), `local_date` (date or null), `precision` and an explanatory `reason`:

| Input | Precision | Result |
|---|---|---|
| Stated date, time, known fixed offset/IANA zone | datetime | UTC instant and original local date |
| Stated date, no time | date | Local date only; no assumed midnight/end-of-day |
| Stated date and time, zone unknown | date | Local date only; reason says the time is not trusted because the zone is unknown |
| Rolling, ambiguous, or no date | unresolved | No instant/selected date, with reason |

For IANA zones, `fold=0` is always used. At a fall-back overlap this selects the first occurrence. At a spring-forward gap it uses the pre-transition offset even though that wall time did not exist; the UTC result is an explicitly flagged interpretation, not a claim of a real local instant. Offset comparison and UTC round-trip detect gaps/overlaps, and `reason` records them and the fold rule. Ordinary dates before/after DST use the database's correct offsets. No input is repaired or mutated. Checklist consumers must not hide these warnings.

## Conservative comparison

`compare(deadline, now)` requires an aware `now`; it never reads today's date or the machine timezone. Datetime precision is unchanged: compare instants (past only strictly after the deadline; equality is upcoming). Unresolved deadlines yield `unknown`.

For precision `date` (both a date without a time and a time with an unknown zone), compare the UTC instant of `now` against a global closing window for the stated local date D:

- `upcoming` only **before D at 10:00 UTC**, the end of D in the easternmost zone UTC+14.
- `past` only **at or after (D + 1 day) at 12:00 UTC**, the end of D in the westernmost zone UTC-12.
- `unknown` throughout the interval between those bounds, including the first bound but excluding the last. The outcome depends on which zone the page meant: **unknown is the safe answer**.

These bounds do not assign a source timezone, invent an exact closing time, or change `resolve`'s date precision. The caller's timezone is irrelevant: the same instant expressed in UTC-12, UTC+05:00 or UTC+14 produces the same comparison. The unreachable known-zone/date-only branch is removed; the model forbids timezone without time, while time with a known zone resolves to datetime precision.

For example, D=21 October and `now`=22 October 01:00 at UTC+05:00 is inside the window and returns `unknown`, never prematurely `past`. The resolver's defensive known-zone check explicitly raises ValueError rather than relying on an assertion, including under Python `-O`.

## Ordering and verification safety

`ordered(iterable)` returns an `OrderedDeadlines`, a **list of resolved Deadline objects**, plus `.unresolved`, a separate list retaining unresolved objects in input order. None are dropped or interleaved into the resolved ordering. UTC instants are sorted chronologically; date-only entries use their date bucket and precede timed entries in the same nominal bucket. This mixed-precision display ordering does not invent midnight or claim an absolute cross-zone ordering for an unknown-zone date. Ties are stable.

Resolution/comparison/ordering do not verify evidence. A deadline is `usable_for_logic` only when status is present and verification is verified, as in ADR 008/010. Unverified/unchecked deadlines still resolve neutrally and retain all quotes, but are not checklist inputs. Ambiguous deadlines are never usable. Gold conversion initializes every deadline to `not_checked`, even if its input dictionary supplies another verification state.

## Deferred to checklist generator #40

No task generation, deadline buffers, reminders, automatic source-zone confirmation, or eligibility logic is implemented. #40 must gate on `usable_for_logic`, carry resolution warnings, require appropriate calendar confirmation, and skip time-based buffers for date-only/unknown-zone/unresolved results. The evidence verifier (#20), not this module, controls verification transitions. No network/LLM calls, real-page fixtures, labels or snapshots are created or modified.
