# 03 — Evaluation Plan (the Discernment layer)

**Status:** Draft v0.2 (reviewed; edits applied)

The credibility of this project rests on measured accuracy. The evaluation set is a first-class deliverable, built **before** the extraction pipeline is tuned.

## 1. Gold set

- **Size:** start with 36 programs (M3), grow to 60+.
- **Selection:** nine program families, **four programs each**: Germany (DAAD-type), United Kingdom (Chevening-type), United States (Fulbright-type), South Korea (GKS-type), China (CSC-type), Erasmus Mundus, Netherlands university scholarships, Japan (MEXT plus foundations), Italy (Politecnico di Milano plus other Italian scholarships). Within each family, vary page layout (clean HTML, JS-heavy, PDF-only, multi-page). English-language pages first.
- **Labeling order:** label the five shortlist families first (CSC, Erasmus Mundus, Netherlands, Japan, Italy), so the tool is useful for your own applications early; then the other four families.
- **Per-family reporting:** with only four programs per family, report metrics per layout type and overall, and treat per-family numbers as indicative, not conclusive.
- **Labeling:** every field hand-labeled by you with the supporting quote; a second pass a week later by you (or a volunteer) to measure label consistency on a 10-program subset.
- **Storage:** `eval/gold/<program_slug>.json` + frozen page snapshot (`eval/snapshots/`) so results do not drift when websites change.
- **Held-out split:** 20% never used while tuning prompts; reported separately.

## 2. Metrics

| Metric | Definition |
|---|---|
| Field precision / recall | Per field, value match vs. gold (normalized) |
| Deadline exact-match | Date **and** deadline type, cycle/year, and timezone equal to gold, per deadline; rolling status correct |
| Evidence presence | % of fields with `verification="verified"` whose quote is found in the cited passage. **Deterministic invariant, target 100%**; any miss is a bug in the verifier, because failures must already have `verification="unverified"`. Content `status="present"` alone does not imply verification |
| Evidence support | % of verified quotes that a human agrees actually **support** the extracted value (sampled audit, 50 fields). **Quality metric, not an invariant**: presence does not prove support |
| Abstention quality | Compare content status with gold (absent/ambiguous/linked versus present); separately audit withholding due to `verification="not_checked"` or `"unverified"`. Failed verification does not imply that gold says absent; the retained value may still be correct |
| Eligibility agreement | Verdict vs. hand-labeled verdict for 5 synthetic profiles per program |
| Dangerous-error rate | Wrong "eligible" verdict, or a wrong deadline shown with `verification="verified"` (tracked separately; should trend to ~0). Includes a verified quote that exists but does not support the value; `status="present"` is not a verification result |
| Confidence usefulness (diagnostic only) | Whether advisory confidence correlates with correctness. Reported for triage; **never used by eligibility** |
| Latency / cost | Median seconds and tokens per program |

## 3. Process

1. Build gold set and harness first (M3). Labeling runs **in parallel** with M1; extraction tuning (M2) does not start until the labeling guide and the first labeled programs exist.
2. Run a naive baseline (single prompt, no verification) → record numbers.
3. Add each pipeline improvement one at a time; keep or revert based on metrics.
4. CI runs the harness on a small fixed subset on every PR and fails if the dangerous-error rate regresses or evidence presence falls below 100%.
5. Publish a results table in the README, with date and model/prompt versions.

## 4. Judge usage

An LLM judge is used only for the *evidence support* audit and always spot-checked by you. Primary metrics are code-computed against hand labels.

## 5. Error analysis log

Keep `docs/error-analysis.md`: for each failure class (e.g., "deadline in a PDF table", "conditions expressed as negation"), note frequency, root cause, fix, and whether it moved the metric. This is the best portfolio content in the repo.
