# Evaluation harness (report version 1)

The harness evaluates extractor content against independently hand-written labels.
It never writes labels, saves/refetches snapshots, judges support or calls a model
by default. See [ADR 016](adr/016-evaluation-harness-failure-semantics.md).
Fictional FakeClient tests establish software contracts, not scholarship accuracy.
The three committed SKELETON files are unfinished and produce no benchmark scores.

## Inputs and execution

From the repository root, choose one selection mode:

```sh
python scripts/run_eval.py --all-labeled
python scripts/run_eval.py --slugs fictional-award,another-fictional-award --out eval/reports/2026-10-30.json
```

These names are fictional examples, not real gold labels. Configure LLM_PROVIDER
and LLM_MODEL to the identity used to create the existing `.cache/llm` entries.
Without `--live`, the configured client is forced to **read_only**, even if the
environment says off/read_write. A missing cache directory is an empty required
cache: every miss becomes unavailable/failed_groups, with zero provider calls;
it does not create the directory or fall back to inference. Replay keys include
schema, prompt, rendering and actual selected passages. New tool output may miss
an old cache. `--cache-dir` selects another private cache directory.

Only the owner may elect `--live`, using LLMConfig.from_env and its configured
cache policy. This permits provider inference, never page fetching. No live run
was performed in this issue. Keys/headers/config dumps are never printed.

`loader.py` reads gold using the gold JSON Schema and canonical Record validators.
It refuses any nested note/notes containing SKELETON (case-insensitive), or
minutes_spent == 0. Underscore examples, malformed labels, filename/slug mismatches
and inconsistent deadline sets are skipped with reasons. Skips are not successes
or absent predictions. Missing requested slugs appear in labels_skipped too.

Snapshots are read-only from `--snapshots-dir` (default eval/snapshots), either
`<slug>.html|pdf` or `fetched/<content_sha256>.html|pdf`. At least one must match
gold's frozen lowercase raw SHA-256 exactly. Missing/mismatched bytes skip that
label; no network recovery or acceptance of benign drift occurs here. Current
tools derive text in memory, ignoring saved .txt copies. The existing snapshots
manifest supplies final_url only for the same slug/raw hash; otherwise gold's
source.url supplies base context. Redirect-dependent relative links may differ
without matching final-URL metadata; keep that metadata for reproducible replay.
No baseline adoption, label migration or snapshot replacement is implemented.

The normal run_pipeline always performs verification. The harness independently
derives its segmented document with the same default configuration for presence
checks and audit context. Unsupported PDFs/empty text have no inference and all
unavailable decisions are excluded with pipeline_unavailable diagnostics.

## Content scoring and confusion table

Normalize BOTH sides with guide 07 §5 before comparing. Explicit dated English
forms (1 May 2027 / May 1, 2027) become ISO; a missing year or ambiguous numeric
date stays unchanged. Explicit AM/PM times become HH:MM; midnight/end of day are
never interpreted. Only guide mappings JST, Beijing time, CET and CEST are
canonicalized. No country-based zone, year, currency, period or GPA conversion.
Explicit degree synonyms follow the guide; Graduate is not mapped to master.
Other text only collapses whitespace, preserving case, wording and nationality
phrases. There is no character-edit/fuzzy matching. Object order and null optional
properties are ignored; collection-valued claims are order-independent multisets
with duplicate multiplicity preserved. Amount and amount_max remain different.

The seven named fields are each one decision per program. A present collection
value (documents/funding/degrees) is one atomic value, not token overlap. For
conditions, score multiset membership by kind/value/required/applies_to, ignoring
evidence and notes; conditions are implicitly present, never an absent status.
The overall field micro score pools seven field decisions and condition items;
per-field results keep these units visible. Collection decision_accuracy measures
the whole set, separate from item precision/recall.

| Gold / prediction | present, same normalized value | present, different value | absent | ambiguous | in_linked_document |
|---|---|---|---|---|---|
| present | TP; exact decision | FP + FN | FN | FN | FN |
| absent | FP | FP | exact decision; no positive | status error; no positive | status error; no positive |
| ambiguous | FP | FP | status error; no positive | exact status decision; no positive | status error; no positive |
| in_linked_document | FP | FP | status error; no positive | status error; no positive | exact only if linked_url also agrees |

Each field also reports the full gold->pred status confusion counts and
decision_accuracy, so successful abstention is not lost in positive-value F1.
Ambiguous candidate notes/quotes are not evaluated as guessed values. P=TP/(TP+FP),
R=TP/(TP+FN), F1=2TP/(2TP+FP+FN). Zero denominator means null/n/a, never 100%.
Verification is an independent axis: retained unverified/not_checked values still
contribute to content scoring (ADR 008), never become usable logic by scoring well.

## Deadlines, exclusions and abstention

Deadline matching is an unordered multiset of **date, type, cycle_year, time,
timezone, rolling and status**, with exact normalized equality on all dimensions.
Labels/notes/evidence are not matching keys. Report TP/FP/FN per deadline,
whole-program set exactness (including deadlines_status), and separate set-level
status agreement/confusion. Rolling deadlines compare null date + rolling=true;
there is no guessed instant or timezone equivalence beyond the guide mappings.
Ambiguous deadlines retain their status/null date, not inferred candidate dates.

**EXTRACTION_FAILED placeholders are not absence.** A failed group excludes its
fields/list from all precision/recall and status/value denominators. A rejected
named field (including URL_NOT_ON_PAGE) excludes only that field, retaining valid
siblings. A rejected deadline/condition cannot be aligned reliably by its provider
index to a gold index; conservatively exclude that program's entire affected list
and set-status comparison. Counts show excluded decisions, gold items and accepted
predicted items. Valid siblings remain in the record, reports and presence audit.
This sacrifices sample size instead of concealing rejection or inventing alignment.
For lists, item counts describe excluded gold and accepted predicted members.
Tables list each failed group/status and each rejection/index/reason, never raw
rejected page/model contents. Excluded counts accompany each scored metric.

Abstention quality reports absent/ambiguous/linked statuses separately. Agreement
means the same gold status (linked target correctness is separately in decision
accuracy). For verification withholding, gold has no verification axis: agreement
means gold is non-present, NOT that human labels imply failed evidence. Report
retained_value_correct alongside agreement; a correct retained value with bad
evidence is still a missed supported extraction. For deadlines, report set-level
abstentions and per-item unverified/not_checked/ambiguous separately, using stated
type/cycle for counterpart claims; conditions use kind. These are abstention
events, not a one-to-one alignment of missing list items. Failures/rejections
are excluded, never rewarded as abstention. No confidence threshold changes
content, verification or any logic; available confidence/correctness pairs are
diagnostic data only, not an eligibility input or calibrated probability. Where
variance/sample size permit it, report Pearson correlation with correctness;
otherwise correlation is null. No confidence threshold changes any claim.

## Presence, danger, latency and counts

For every evidence quote on a verified claim, an independent normalization/slice
oracle checks the original document offsets and cited passage endpoint overlap.
It allows only ADR 012 formatting (including NFKC, soft/zero-width removal and
literal line-break hyphen joining). Missing reports/citations, edited/missing
quotes or invalid ranges are listed loudly as **VERIFIER BUGS**, not quietly
scored as abstention. Presence rate must be 100%; it is null when there are no
verified quotes. Every quote on a multi-quote claim counts. Excluded content
decisions do not hide a verified sibling's presence bug.

Dangerous errors list each verified field/deadline/condition whose normalized
claim disagrees with gold, including slug, field, prediction, gold and quotes.
The rate denominator is comparable verified claims; the error list remains
visible for verified valid list siblings even when list accuracy was excluded.
A wrong unverified value is still an ordinary content error, not dangerous here.
This is a gold-disagreement metric, not a safety or support guarantee. No
eligibility verdict is assessed.

Pipeline wall seconds (monotonic timer around run_pipeline) and ExtractionResult
input/output token counts are reported per program and per layout/overall, with
known/unknown counts and medians. Missing token usage is unknown, never zero;
known sums need not be complete. Cached usage is replayed response metadata, not
new billed tokens, and provider retry totals are not available. No currency cost
is invented. There is no defensible per-field attribution of shared group tokens.

Observable layout buckets are html, html_table (a retained tr span), pdf and
pdf_multi_page. These do not claim JS-heavy/multi-page-site detection; that needs
explicit curated metadata outside the current gold schema. JSON includes
per-field accuracy, presence, abstention, danger and confidence results within
each layout and overall; Markdown includes a README-sized
results table, per-field counts, failures and every dangerous error/verifier bug.
Always read n/exclusions before percentages. Per-family/held-out inference and
statistical significance are not claimed for a tiny pilot.

## Private reports and human support audit

The default artifacts are eval/reports/<UTC-date>.json, .md and -audit.csv. JSON
records the git commit and dirty-worktree flag, configured model/provider, current
cleaner/PDF/segmenter/verifier/rendering versions,
per-program prompt versions/model/provider, source hashes, used/skipped labels,
truncation, suspicious-passage diagnostics and metrics. The audit seed defaults
to 1729 (`--seed` changes it). Up to 50 verified claims are sampled without
replacement in a reproducible, input-order-independent way; all quotes for each
selected claim are retained. Audit columns: slug, field, value, quote, passage
context, blank supports_value (y/n), blank notes. The human fills those columns;
the harness never judges or estimates support. Import untrusted CSV context as
text, never as executable spreadsheet formulas.

**eval/reports/* is git-ignored except .gitkeep.** Reports are not committed unless
the owner explicitly approves. Audit context contains private page text: review
and redact before any sharing; do not publish it as a normal metrics artifact.
Snapshots must never be committed. Output guards refuse gold/snapshot/cache
directories (including custom input directories and resolved output symlinks).
Exit 0 means the report was produced, even with no labels, misses or verifier
bugs; it is not a quality gate. Exit 1 is a script/configuration/file error.

Not done here: real labeled baseline/accuracy claims, eligibility agreement,
CI regression gating (#32), held-out split enforcement, support judging, live
provider adversarial compliance, baseline adoption or prompt-registry work.
