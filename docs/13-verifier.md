# Evidence verifier (version 1)

`verify_record(record, doc) -> (RequirementRecord, VerificationReport)` is pure,
deterministic code. It returns a deep independent record and never mutates either
input, reads files, calls a network/LLM, or interprets untrusted page instructions.
`VERIFIER_VERSION = "1"`; changing matching rules requires a version bump.

## Presence, not support

Verification proves **quote presence only**, not that a quote supports a value,
that a value is correct, or that the source is authoritative/current. Support
remains the human-audited metric in doc 03. A real, unrelated quote can pass.
All quotes on an item must pass; one failure makes the item `unverified`.
Recompute every evidence-bearing Field, Deadline and Condition, ignoring any
incoming verification state. Absent/linked fields stay `not_checked`.
Values, quotes, passage IDs, context, confidence and metadata are never repaired
or dropped. `usable_for_logic` still gates claims according to ADR 008/010.

## Outcomes and precedence

1. `invalid_quote`: normalized quote has fewer than six characters or two Unicode
   letter/number tokens, or contains `...`, `…` or `[...]`. No stitched evidence.
2. `no_passage_cited`: nullable/unknown passage ID. Suggest passage IDs only if
   the quote has exactly one document occurrence; never repair its citation.
3. `exact`: verbatim presence within the cited passage.
4. `normalized`: formatting-only presence within the cited passage.
5. `spans_passages`: a contiguous exact/normalized match starts or ends inside the
   cited passage and extends into adjacent passages. Search unchanged document
   text, including separator whitespace, and report all touched passage IDs.
   A match enclosing the cited passage with **both** endpoints outside does not
   qualify. No joining noncontiguous fragments or skipping intervening words.
6. `found_in_other_passage`: presence elsewhere, not qualifying in the cited
   window; fail and suggest document-ordered passage IDs.
7. `not_found`: no permitted match; fail.

Only exact, normalized and spans_passages verify. Count duplicate matches at the
first successful outcome tier (including overlapping occurrences); normalized
variants cannot override an available verbatim match. An exact and a narrower
normalized range for the same physical occurrence are not double-counted.
Normalized `context_before`/`context_after`, when supplied, must match immediately
before/after a candidate to uniquely select it. Context is a locator hint, never
an extra claim or a reason to erase real presence. A unique contextual match takes
precedence in location selection within the selected tier; otherwise prefer the
first verbatim match, then the first normalized one. `occurrences` is the tier's count;
`ambiguous_location` is false only for one occurrence or unique context selection.
The reported exact/normalized outcome describes the selected occurrence.

## Normalization and offsets

Apply the same rules to source and quote: remove a literal ASCII hyphen immediately
followed by LF/CRLF (not hyphen + spaces + newline); remove soft hyphen U+00AD and
U+200B–U+200D/U+2060/U+FEFF; Unicode NFKC; map curly single/double quotation marks
and en/em dashes to ASCII; collapse NBSP/all whitespace runs to one space and
strip boundary whitespace. Do not change case, fold digits/letters or homoglyphs,
translate, or permit character-edit tolerance. NFKC's defined compatibility
equivalences (such as fullwidth digits and ligatures) are allowed, not arbitrary
digit substitutions. A changed `3.5`/`3.6` or `2027`/`2026` must fail: a one-digit
error can change eligibility or a deadline despite tiny edit distance.

The normalizer tracks each normalized character back to its original range,
including canonical composition/reordering and compatibility expansions. Every
candidate's original slice is independently re-normalized before acceptance;
partial ligature expansions cannot falsely certify a different original slice.
All report offsets are half-open Python character offsets into **doc.text**, not
normalized-string, HTML-byte, or PDF-byte offsets. Source maps remain untouched.

## Report and limits

Frozen report/item dataclasses hold owner path (`fields.program_name`,
`deadlines[1]`, `conditions[0]`), evidence index, unchanged quote, outcome,
`matched=(start,end)` or null, touched `passage_ids`, `suggested_passage_ids`,
occurrence count, ambiguity, and optional `near_match`. Only successful matches
receive matched offsets/touched IDs; failed locations are suggestions, not proof.
Totals include every outcome (including zero counts) and `verifier_version`.
Items are ordered by sorted field name, deadline index, condition index, then
evidence index. Multiple locations default to a deterministic first occurrence.

The optional edit-distance diagnostic is deliberately **not implemented**:
`near_match` is always null, and no edit-distance library/dependency is added.
There is no network, LLM, extractor, support judge, or eligibility/checklist
engine here. Hand labels and private snapshots are not modified. Adversarial
synthetic HTML/generated PDF tests and an independent whole-string NFKC oracle
check presence and original-offset round trips on 200 seeded records.
