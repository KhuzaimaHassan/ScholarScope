# ADR 018 — Private profile schema and no GPA conversion

**Status:** Accepted · **Date:** 2026-11-01

## Context

The deterministic eligibility engine needs owner-provided degree, GPA scales,
nationalities, language results and document holdings. Missing data must remain
missing. Converting a GPA between scales without an approved interpretation
would invent a fact. Private applicant data must remain separate from public
gold labels, source snapshots and provider extraction requests.

## Decision

- Use frozen, strict Pydantic v2 `Profile`, `GPAEntry`, `LanguageScore` and
  `DocumentHeld` models in `scholarscope.profile`, with extra fields forbidden
  and non-finite numbers rejected. No I/O, logging or rule evaluation.
- Import the Requirement Record's degree vocabulary and its language-test
  string type. It has no test or document enum to duplicate. Preserve test names;
  document kinds only collapse/strip whitespace and lowercase, without synonyms.
- Store each GPA as its explicitly supplied finite value and positive scale;
  reject value above scale and duplicate `(value, scale)` pairs. No conversion,
  normalization of the scale itself, or rounding. Numeric `4` and `4.0` compare
  alike under the same strict float representation used by Condition `GPAValue`.
- Scale helpers return exact-scale entries or `no_comparable_scale` information,
  never an eligibility verdict. A 4-point entry does not answer a 100-point query.
- Nationalities use a bundled, reviewable set of 249 assigned uppercase ISO
  alpha-2 codes; no live lookup, aliases or inferred nationality. Duplicate codes
  are rejected. Membership does not decide nationality eligibility.
- Optional values default to `None`; empty tuples mean no entries supplied, not
  affirmative absence. Explicit zero/empty values stay distinct from missing data.
- Redact model repr/str and validation errors, including nested values and
  arbitrary input keys. Only explicit dump methods reveal values. Profiles must
  never be sent to an LLM; test the absence of extraction/provider dependencies.
- Add public JSON Schema metadata and ignore `profiles/` and `*.profile.json`.
  Do not implement persistence, deletion endpoints, rules or verdicts in #35.

## Consequences

This implements the profile input contract for ADR 004's deterministic engine,
without changing ADR 010's evidence states. It fulfills issue #35's GPA scale
normalization as numeric representation equality only, consistent with labeling
guide 07 §5's no-conversion rule. Missing or differently scaled GPA data still
needs a conservative rule decision and provenance in later issues.

Snapshots/gold labels remain separate and unchanged. Ignore rules and redacted
representations are safeguards, not authorization or encryption: callers must not
serialize profiles into logs, public reports or model requests. A future storage
design must implement access control, private paths and deletion separately.
