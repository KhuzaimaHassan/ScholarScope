# ADR 024 — Evidence-matched scoring alongside unchanged strict scoring

**Status:** Accepted · **Date:** 2026-11-11

**Owner-authorized amendment — 2026-11-11 (same day):** shared field-level
funding quotes make evidence pairing uninformative: each cost entry can overlap
every entry on the other side. For funding_coverage only, replace evidence
pairing with exact normalized `item` pairing, one-to-one, with duplicates paired
in ascending original index order. Funding pairing uses no evidence overlap.
Conditions and deadlines retain the containment rules below. Strict scoring
and its frozen results are unchanged.

## Context and scope

The owner fixed these rules before the next cached comparison, for all labels.
Free-text disagreement can inflate exact-match errors. Add a parallel diagnostic
mode without replacing the historical measure or claiming semantic support.
AI-assisted labels remain provisional and cannot establish an independent baseline.

## Strict contract retained verbatim

These exact sentences in [ADR 016](016-evaluation-harness-failure-semantics.md)
remain binding for **strict**:

- "Apply guide 07 §5 normalization symmetrically, without fuzzy matching,
  year/zone guessing or money/GPA conversion."
- "Compare retained content independently of verification."
- "Count exact positive claims and explicit status confusion; wrong present
  values count FP+FN."
- "Match list items as multisets, preserve multiplicity, and show exact
  set/program decisions as well as item counts."
- "List verified claim disagreements with gold as dangerous errors; do not claim
  value support, source truth or eligibility safety."

These exact sentences in [doc 18](../18-evaluation-harness.md) also remain
**strict**, unchanged:

- "Other text only collapses whitespace, preserving case, wording and
  nationality phrases."
- "A present collection value (documents/funding/degrees) is one atomic value,
  not token overlap."
- "For conditions, score multiset membership by kind/value/required/applies_to,
  ignoring evidence and notes; conditions are implicitly present, never an
  absent status."
- "Labels/notes/evidence are not matching keys."
- "Dangerous errors list each verified field/deadline/condition whose normalized
  claim disagrees with gold, including slug, field, prediction, gold and quotes."

The failed/rejected exclusions and independent presence oracle also remain.
ADR 024 adds the following separately named mode; it does not revise strict
numbers or any of those sentences.

## Evidence-matched mode

1. Pair conditions and deadlines using evidence only.
   Reuse the presence oracle's `quote_normalize` exactly, including NFKC,
   whitespace collapse, soft/zero-width removal, literal line-break hyphen
   joining and its existing smart-punctuation mapping. Ignore empty normalized
   quotes. Some quote on either side must equal or literally contain a quote on
   the other side. No case folding of quotes, token overlap, threshold, edit
   distance, inference, translation or fuzzy matching.
2. Carry original gold/prediction indices as stable identities. Enumerating
   those indexed items or candidate edges in a different order cannot alter
   output. Reassigning indices changes the specified input and its tie-breaks.
   Sort candidate edges by exact-quote equality first, then descending maximum
   contained-quote length, then equal `kind`, then ascending gold index, then
   ascending predicted index. `kind` is the literal condition property;
   deadline items have no such property and receive no category/type bonus.
   Greedily accept an edge only if both endpoints are unused. One prediction
   containing two gold quotes gets only one pair; length/kind/index priorities
   choose it, and the unpaired gold is FN. This is deterministic, not an optimal
   bipartite assignment or a proof of support.
   Funding_coverage instead groups entries by exact `item` after the existing
   guide 07 §5 value normalization, without case folding or category inference.
   Within each item group, pair ascending gold indices with ascending predicted
   indices up to the smaller group size. Surplus entries remain unpaired. Do
   not inspect quotes, amounts, currency, period or note to choose funding pairs.
   Paired amounts, currency and period are still compared under rule 3.
3. Compare paired structured projections exactly after existing guide 07 §5
   normalization. Conditions compare kind, required, applies_to presence
   (nonempty after whitespace normalization), numeric/boolean JSON leaves and
   the typed GPA/language structures, including language-test identifiers and
   logic. Free-text kinds' string values do not determine correctness. Funding
   compares item, amount, amount_max, currency and period; deadlines compare
   type, cycle_year, date, time, timezone, rolling and status. Missing/null
   optional properties retain existing normalization semantics. No conversion
   or numeric tolerance is introduced.
4. Collect exact free-text agreement separately as **advisory text agreement**:
   free-text condition value leaves, applies_to wording, funding note, notes and
   labels. It never changes TP/FP/FN, verification, pairing or dangerous errors.
   Compare text after the existing whitespace-only value normalization, with
   missing/null optional properties treated consistently. No semantic judgement.
   Each named field's notes add at most one advisory observation, separate from
   its paired entries; missing text on both sides adds no observation.
5. Only in this mode, normalize required_documents strings with case folding,
   whitespace collapse and removal of one leading standalone a/an/the. Compare
   the resulting multiset, retaining duplicates. Other named fields retain
   strict decisions; their fixed field names establish correspondence. The
   funding field expands to entry-level decisions, including explicit set
   status agreement. Field P/R/F1 pools named fields/funding entries/conditions;
   deadlines keep a separate total as in strict. Report per-field counts and
   denominators; the two modes have different units for funding.
6. Paired equal structured projections are TP; a structured mismatch is FP+FN.
   Unpaired gold is FN; unpaired prediction is FP. A VERIFIED paired item with
   structured disagreement, or a VERIFIED unpaired prediction, is an
   evidence-matched dangerous error. Separate condition `kind` disagreements
   into their own count/list (label-judgement cases); count other structured
   disagreements separately, including funding values and deadline type. An item
   can appear in both lists if both classes disagree; the combined error count
   counts the item once. Unpaired verified errors have their own reason.
7. Inherit strict exclusion flags unchanged: failed groups and rejected named
   fields are excluded; rejected condition/deadline lists are excluded as whole
   sets, with valid retained siblings still independently audited for danger.
   No rejected index is aligned to a gold index or repaired. Rejected funding
   entries retain strict's existing named-field/list distinction. Empty
   denominators stay null. Neither mode changes extraction or verification.

## Limitations

Free-text condition values are not checked for correctness in this mode. A
right-quote, wrong-value free-text condition therefore scores correct when its
structured properties agree; the text difference is advisory only. Quote
containment has no minimum quote length: any nonempty normalized quote can
participate, even a very short one. Neither pairing rule proves semantic support.

## Reporting and validation

Bump the JSON report version. Keep every existing strict section and number,
label them **strict**, and add **evidence-matched** beside them in JSON,
Markdown and console. Preserve label ID/pass provenance and the exact
AI-assisted warning header. Labeling minutes remain outside metrics. Keep
private raw quotes/context out of committed reports; the owner authorized only
comparison tables and the evidence-matched error list in the PR description.

Fictional tests cover containment and normalization, order/tie rules, unique
endpoint use, text-only differences, structured and kind errors, document
articles, verified unpaired claims, exclusions and byte-identical strict fixture
scores against the pre-change scorer. Rescore the frozen local input using
read-only cache only. No provider calls, prompt changes, label edits, snapshot
edits, extractor changes, fuzzy matching or new dependencies.
