# ADR 016 — Evaluation failure semantics and private audit artifacts

**Status:** Accepted · **Date:** 2026-10-30

## Context

The group extractor preserves failed calls and rejected items separately from
page absence (ADR 013). Gold labels distinguish content status, not verifier
state (ADR 010), and retained unverified values remain measurable (ADR 008).
Treating failure placeholders as absent would inflate abstention quality and
distort precision/recall. Quote presence alone never establishes support
(ADR 003/012); support still needs an independent human audit. Snapshots and
page context remain private under ADR 007/015.

## Decision

Owner-authorized extension (2026-11-11): this ADR's scoring sentences remain
unchanged for **strict** mode. [ADR 024](024-evidence-matched-scoring.md) adds a
parallel **evidence-matched** diagnostic with literal quote-containment pairing
for conditions/deadlines, exact funding-item pairing and structured comparisons.
It does not replace strict results or alter the
failure exclusions, presence oracle, privacy boundaries or AI-assisted warning.

Use schema-validated, hand-written labels and exact-hash local bytes only.
Owner-authorized amendment (2026-11-10): diagnostic comparisons may also use
explicitly AI-assisted labels. Record every used label's ID/pass, and when any
ID contains ai-assisted, mark console and JSON/Markdown report headers with
"LABELS NOT INDEPENDENT (AI-assisted): results are provisional, not a baseline".
This does not turn an AI-assisted label into an independent hand label. Never
use labeling minutes as a metric, weight or substitute for pipeline latency.
Skip any label with a SKELETON note or zero labeling minutes, with explicit
reasons. Never fetch, rewrite labels, save snapshots or adopt a new baseline.
Force read_only cache replay by default, including on a missing cache directory;
report misses as failed groups, never fall back to inference. Only an explicit
owner --live run may call the configured provider. Tests use FakeClient and
synthetic temporary files with sockets prohibited.

Apply guide 07 §5 normalization symmetrically, without fuzzy matching, year/zone
guessing or money/GPA conversion. Compare retained content independently of
verification. Count exact positive claims and explicit status confusion; wrong
present values count FP+FN. Match list items as multisets, preserve multiplicity,
and show exact set/program decisions as well as item counts.

Exclude failed groups and rejected named fields from accuracy and abstention
denominators. Rejected list indices are not gold indices: exclude the affected
program's whole deadline/condition list and deadline-set comparison, preserving
valid siblings for independent presence checks and dangerous-error diagnostics.
Show excluded decisions/items alongside metrics and failures in their own table.
Empty denominators are null, not perfect results. Verification withholding is
not a gold verification label; separately record retained-value correctness.

Independently check every verified quote's presence at reported original offsets
overlapping its citation. Any miss is a loud verifier bug. List verified claim
disagreements with gold as dangerous errors; do not claim value support, source
truth or eligibility safety. Export a seeded sample of up to 50 verified claims
with all quotes and private context, leaving human support/notes columns blank.

Record git/tool/prompt/rendering/model provenance, label skips, counts, layouts,
truncation, latency and known/unknown tokens in JSON and Markdown. Observed static
layout buckets are not guesses about JS dependence. Reports and audit CSVs are
ignored except .gitkeep and require owner approval before publication; audit
context requires privacy/copyright review. CLI exit status reports execution,
not quality; a CI quality gate is separate work.

## Consequences

Failures cannot masquerade as correct abstention, at the cost of conservative
list exclusions and potentially small denominators. Cached-response usage is
not billing, and fictional tests are not measured product accuracy. Eligibility,
support judging, held-out enforcement, CI gates, live adversarial evaluation and
baseline adoption remain deferred. See [doc 18](../18-evaluation-harness.md).
