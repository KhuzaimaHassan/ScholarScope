# Profile schema (version 0.1)

`scholarscope.profile` defines frozen, strict Pydantic v2 data models for information
provided by the owner. It performs no rule evaluation, I/O, logging, extraction,
or LLM calls. Unknown properties and non-finite numbers are rejected. Optional
values remain `None` until supplied; no nationality, degree, GPA scale, test,
birth date, or experience is inferred.

## Fields and vocabularies

| Field | Shape and constraints |
|---|---|
| `id` | Opaque owner-assigned token, 1–128 ASCII letters/digits/underscore/hyphen. Never put a name, email, birth date or other personal data here; syntax cannot establish that a token is anonymous. |
| `schema_version` | `"0.1"` |
| `degree_level` | Optional imported `scholarscope.schema.DegreeLevel`: bachelor/master/phd/postdoc/other; no duplicated enum or degree inference |
| `field_of_study` | Optional free text, maximum 200 characters; wording preserved |
| `gpas` | Tuple of `GPAEntry {value, scale, label?}`. Value is finite and at least zero; scale is finite and positive; value cannot exceed scale. Label maximum 200 characters. Identical `(value, scale)` pairs are rejected even with different labels. |
| `nationalities` | Tuple of uppercase assigned ISO 3166-1 alpha-2 codes, checked against the bundled 249-code set. Duplicates, lowercase, aliases, historical/reserved codes and unassigned codes are rejected. The list includes territories; it is a code validation set, not an eligibility rule. |
| `language_scores` | Tuple of `LanguageScore {test, score, sub_scores?, test_date?}`. `test` reuses `LanguageOption.test`'s imported `NonEmptyString` type and additionally rejects whitespace-only names. The Requirement Record has no language-test enum: IELTS/TOEFL variants and other explicit names remain as supplied. Score and named sub-scores are finite and nonnegative; no inferred scale or per-test upper bound. |
| `documents` | Tuple of `DocumentHeld {kind, note?}`. Requirement Record documents are strings, with no controlled enum. Local `kind` strips/collapses whitespace and lowercases, maximum 200 characters; no synonym mapping (`cv` and `résumé` stay distinct). Note maximum 1,000 characters. |
| `date_of_birth` | Optional calendar date; no age calculation in this issue |
| `years_experience` | Optional finite number at least zero; no experience verdict |

`None` means **not provided**, distinct from zero, empty text or an empty mapping.
For example, missing experience differs from explicitly supplied `0`. Optional
free text and notes may be empty. Collection defaults are empty tuples, meaning
**no entries supplied**, not a factual assertion that the owner has no degrees,
nationalities, test results or documents. A missing sub-score mapping (`None`)
differs from a supplied empty mapping (`{}`). Sub-score mappings are copied and
made read-only; the nested models and tuple collections are immutable too.

Python inputs use tuples and date objects; strict validation rejects stringified
numbers, booleans as numbers and Python lists in tuple fields. JSON uses arrays
and ISO `YYYY-MM-DD` dates. The JSON loader explicitly decodes these representations
because Pydantic's strict JSON tuple/date handling changes inside an error-redacting
wrap validator; this does not relax strict Python input validation.

## GPA comparison data, without conversion

Guide 07 §5 says to keep GPA `{value, scale}` as stated. Condition `GPAValue` uses
strict finite floats, so integer `4` and floating-point `4.0` have the same numeric
representation. Profile GPA entries and scale queries use the same strict float
semantics. There is no rounding, epsilon tolerance, percentage conversion or
rescaling. A supplied float retains its precision as represented in Python.

`gpa_entries_for_scale(profile, scale)` returns entries whose scales compare
exactly equal, in their input order. Both `4`/`4.0` and `100`/`100.0` agree.
An entry `3.5/4.0` is **not** returned for a requirement on a `100` scale.
`match_gpa_scale(profile, scale)` returns `GPAScaleMatch` with status
`comparable_scale` and entries, or `no_comparable_scale` and an empty tuple.
These are data-availability results, not eligibility verdicts. A future engine
must handle missing comparable data conservatively and cite rule provenance;
this PR implements no rule or verdict and grants no conversion policy.

## Privacy invariants

- **Profile data must never be sent to an LLM.** Profile imports no extraction or
  LLM module. A dependency test checks its local transitive imports; this module
  offers no provider or pipeline integration. Future code must preserve this
  boundary; a Python model cannot prevent a caller from explicitly misusing data.
- Model `repr` and `str`, including nested models, contain only the class name
  and `<redacted>`. Do not log profiles, serialized dumps, or their contents.
- Validation diagnostics expose only known field names/indices and constraint
  codes. Raw inputs, arbitrary mapping keys and exception contexts are removed
  from the emitted error payload, including `errors()`/`json()` and malformed-JSON
  errors from `model_validate_json`. No submitted values appear in error messages.
- Explicit `model_dump()` and `model_dump_json()` expose the real values for
  private, intentional use. They are not logging-safe. Pydantic's trusted bypass
  methods (`model_construct`, `model_copy(update=...)`) are not input validators.
- `.gitignore` includes `profiles/` and `*.profile.json`. Do not commit profile
  data. Ignore rules do not remove already tracked files or prevent force-add.
- No load/save helper is implemented. There is therefore no path that writes
  profile data into the tracked tree, gold labels or snapshots through this module.

## JSON Schema and boundaries

`to_json_schema()` uses `Profile.model_json_schema(by_alias=True)`, the same
export mechanism as the Requirement Record. The checked-in public contract is
`eval/schema/profile.schema.json`; a test compares it with the model export.
It contains only schema metadata and the bundled country codes, never profiles.
Cross-field bounds and duplicate GPA-pair rejection also run locally in Pydantic.

To regenerate the contract locally:

```python
import json
from pathlib import Path
from scholarscope.profile import to_json_schema

Path("eval/schema/profile.schema.json").write_text(
    json.dumps(to_json_schema(), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
```

Not implemented: eligibility rules/verdicts (#36), provenance registry (#37),
document matching (#41), storage, authentication, or delete-my-data endpoint
(#49). No LLM or live source call, gold-label edit or snapshot is needed.
See [ADR 018](adr/018-profile-schema-and-no-gpa-conversion.md).
