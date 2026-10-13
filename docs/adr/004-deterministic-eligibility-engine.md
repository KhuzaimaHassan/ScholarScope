# ADR 004 — Deterministic eligibility engine

**Status:** Accepted · **Date:** 2026-10-12

## Context
A wrong eligibility verdict can cost an applicant an entire cycle. Verdicts must be reproducible, explainable, and testable.

## Decision
Eligibility is computed by a **rule engine in code** over `(RequirementRecord, Profile)`, returning `eligible`, `not_eligible`, or `unclear` with reasons.

- Only **verified** fields are used. A rule that needs an `unverified` or missing field returns `unclear`.
- **LLM confidence never influences a verdict.** It is advisory display and triage data only.
- Unknown data produces `unclear`, never a guess.
- Every verdict lists the rule ID and version it used, and each reason links to its source quote (see ADR 009).

## Consequences
- Verdicts are auditable and unit-testable; the same inputs always give the same output.
- Coverage is limited to rules written in code; unusual conditions surface as `unclear` with the source quote for the user to read.
- Rule interpretation (for example GPA scale conversion) is a human decision that must be documented.

## Alternatives considered
- Letting the LLM decide eligibility: flexible but unauditable and prone to confident errors.
- Hybrid with LLM-suggested rules: possible later, but rules would still be reviewed and merged by a human.
