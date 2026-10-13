# ADR 009 — Provenance for every eligibility rule

**Status:** Accepted · **Date:** 2026-10-12

## Context
Rule interpretation is where subtle errors hide: for example how a GPA on one scale maps to a program's minimum, or how a nationality condition is read. These interpretations are human decisions and must be auditable later.

## Decision
Each rule in the engine has a **provenance record**:
- stable ID and version,
- plain-language description,
- rationale for the interpretation,
- source note (program wording, common convention, or the owner's decision),
- link to its unit tests.

Every verdict stores the `rule_id` and `rule_version` used. Changing a rule's interpretation bumps its version and requires an updated test and rationale before merge.

## Consequences
- Any verdict can be explained and reproduced, and rule changes are reviewable in pull requests.
- Writing provenance adds small overhead per rule, which is intended.
- Old verdicts remain interpretable even after rules change.

## Alternatives considered
- Rules documented only in code comments: easy to drift and not queryable.
- A separate rules wiki: likely to fall out of sync with the code.
