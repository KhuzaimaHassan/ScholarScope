# Requirement Record (schema version 0.1)

`scholarscope.schema` defines strict Pydantic v2 models for structured extractor output. They make no network/LLM calls and do not verify evidence or decide eligibility. Unknown properties, invalid shapes and inconsistent field states are rejected, not repaired. See [ADR 010](adr/010-two-axis-field-status.md).

## Record and field shapes

The Record keeps the gold label's nested `fields` structure, plus `source`, `deadlines_status`, `deadlines`, `conditions`, and `schema_version="0.1"`. Extractor metadata `prompt_version` and `model` is nullable. Label-only `program_slug`, `slot`, `labeler`, and `notes` are optional and preserved by conversion for comparison; no label files are written.

| Field | Value shape |
|---|---|
| `fields.program_name`, `fields.institution`, `fields.application_link` | string |
| `fields.degree_levels` | list of bachelor/master/phd/postdoc/other |
| `fields.funding_coverage` | list of `{item, amount?, amount_max?, currency?, period?, note?}`, with doc 07's item/period vocabulary |
| `fields.required_documents` | list of strings |
| `fields.recommenders` | `{count_min?, count_max?, type?}` |
| `conditions` | list of `{kind, value, required, applies_to, evidence, notes?}`; GPA is `{value, scale}`, language is `{logic, options: [{test, min_overall, min_subscore?}]}`; other kinds preserve JSON values without invented normalization |
| `deadlines` | list of `{label, type, cycle_year, date, time, timezone, rolling, status, evidence, notes?}`; status present/ambiguous |
| `source` | `{url, retrieved_on, content_sha256, format, page_state}`; optional gold metadata language/cycle_label/is_mirror/owner_org |

Each generic `Field[T]` adds `status`, `verification`, `evidence`, `linked_url`, `notes`, and `confidence` to its nullable value. Evidence is a list of `{quote, passage_id?, locator?}`; quotes are 1–400 characters. Nullable passage IDs await #13. Gold's optional `context_before`/`context_after` (at most 80 characters each) are preserved. There are no evidence offsets.

## Two independent axes

| Content status | Value | Evidence | Additional rule |
|---|---|---|---|
| present | non-empty | at least one quote | not evidence verification |
| absent | null | empty | verification must be not_checked |
| ambiguous | null | at least one quote | no guessed/candidate value |
| in_linked_document | null | empty | linked_url required; verification not_checked |

Verification defaults to `not_checked`. Only deterministic verifier #20 sets `verified` or `unverified`; both require evidence. The model accepts and validates these states but cannot authenticate their producer. Failed verification retains the value and quote. `usable_for_logic` is a derived Python property, true only when status is present **and** verification is verified; it is not a writable or serialized model field. Confidence is advisory only, never a logic input. No eligibility/checklist engine is implemented here.

## Gold conversion and JSON Schema

`from_gold_label(dict) -> RequirementRecord` copies a label without mutating it and sets every generic field's and deadline's verification to `not_checked`. It preserves content values, quotes, links, conditions, deadlines, source and label metadata. It is a structural converter, not a replacement for the hand-label validator; conversion does not certify a skeleton as labeled. Gold files and snapshots remain untouched.

`to_json_schema()` exports a local JSON Schema. A regression test compares all gold-schema property names (including nested source, evidence and label metadata) with the exported schema, checks the seven claim-field names exactly, and exercises the fictional example. Typed value constraints supplement the gold schema's deliberately permissive `value` property according to doc 07. JSON round trips preserve the `pass` alias in labeler metadata.

## Deliberately deferred

- **#17 implemented:** [Deadline validation and resolution](11-deadlines.md) now cover timezone recognition, rolling/date/time rules, exact duplicate rejection, verifier-owned deadline state and neutral resolution/comparison/ordering. Buffers and checklist generation remain #40; no year/timezone is inferred.
- **#19:** LLM calls, prompts/retries, provider handling, and ensuring extractor output cannot claim verifier authority.
- **#20:** quote matching, evidence presence/support checks, and deterministic verification transitions. `present` does not mean verified. Conditions/deadlines keep gold's structural shapes; this issue does not make them usable for decision logic.

No evidence matcher, segmenter, rule engine, hand-label generation, or live source fetching is included. `scripts/create_issues.py` reads acceptance criteria directly from doc 05; its parser is regression-tested against the amended #16 row, with no duplicated acceptance string to update and no issues regenerated.
