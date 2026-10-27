# Extractor v0: one prompt per field group

The baseline makes five `generate_structured` calls, in fixed order: identity
(program_name, institution, application_link, degree_levels), funding
(funding_coverage), documents (required_documents, recommenders), deadlines, and
conditions. Each group has one trusted v1 prompt. Provider retries and caching
remain the LLM interface's responsibility; there is no additional retry loop.
Temperature is zero. Provider/model identity and all five prompt versions are
recorded. Token totals sum the usage returned by the five calls; missing counts
remain unknown, and provider-layer usage is not an aggregate bill for retries.

## Wire schemas and canonical records

`scholarscope/extraction/wire.py` defines small Pydantic provider models: plain
types, enums, arrays, nullable properties, and shared definitions/references. All
properties are required, including nullable ones. The Gemini supported-keyword
guard is tested on every group schema. No constrained strings, defaults, consts,
discriminators or schema-stripping workaround is sent to a provider. Keyword
compatibility does not guarantee acceptance of every schema/model combination;
provider schema-complexity errors remain explicit failures.

Generic fields retain the canonical status/value/evidence/linked_url/notes shape.
Evidence in wire output has quote and passage_id. Deadlines have the canonical
deadline properties and a set-level deadlines_status; conditions retain their
kind/value/required/applies_to/evidence shape. Conditions have no status: they are
implicitly present claims, with required flags preserved for the rule engine.
Wire models ignore extra properties, including claimed verification. This is a
data boundary, not an injection defense or a way to extend the canonical model.

`convert.py` then enforces **all** canonical domain constraints locally. Every
accepted field, deadline and condition starts at verification `not_checked`.
Conversion never promotes verification. Invalid fields/items and duplicate
deadlines are reported in `rejected_items` with group, original index (or field
name), reason and raw item; valid siblings remain. Do not publish rejected raw
items without reviewing their untrusted contents. Structural wire failures are
retried by the client and can fail the group; partial acceptance applies to
domain validation after successful wire parsing, not malformed JSON.

The existing canonical `Source` is also exported as `SourceInfo`; no second source
contract is introduced. The canonical record has no set-level deadline link/note
properties, so those wire metadata are retained in record.notes. Linked deadlines
remain an empty list with deadlines_status `in_linked_document`; no fake deadline
is created. Inconsistent deadline sets are explicitly rejected.

## Failure semantics: empty does not mean unstated

**Consumers MUST inspect failed_groups, group_status and rejected_items.**
UI and evaluation code must not treat an extraction failure as the page stating
nothing. For invalid_output, provider_error or unavailable, the affected generic
fields use absent/null/empty evidence placeholders, with notes starting exactly
`EXTRACTION_FAILED:<group>:<status>`. The group is in failed_groups. The marker
also appears in record.notes (necessary for failed deadline/condition lists,
which cannot carry a fabricated absent item). Other groups continue unchanged.

Groups are ok if conversion succeeds, partial if valid claims survive rejected
siblings, and failed if a call fails or all attempted claims are rejected. Local
rejections use `EXTRACTION_REJECTED` notes and remain available in rejected_items;
a wholly rejected group additionally has an invalid_output failure marker.
An intentionally empty, successfully extracted list is ok, not a failed group.

`pipeline.run_pipeline` accepts a FetchResult containing bytes; it does no
fetching or writing. It cleans HTML or extracts PDF text, segments, extracts,
and **always calls verify_record** before returning a final record. The separate
ExtractionResult.record remains the unchecked draft. Unsupported/scanned/encrypted
PDFs, empty text and failed fetches return clear statuses without any LLM call.
Versions include cleaner/PDF extractor (whichever ran), segmenter, verifier,
prompt versions, provider and model. Input hash/format mismatches are rejected.

Verified proves quote **presence only**, never that the value is supported.
Fabricated or edited quotes become unverified with values/citations retained.
Only the verifier sets this state; unchecked or unverified claims are unusable
for downstream logic under ADR 008/010.

## Input selection and prompts

`max_input_chars=30000` is a per-group **soft target** for whole passage text
characters, not tokens or JSON/prompt overhead. Keep the first passage and every
passage containing an HTML heading node. Select remaining passages by the count
of distinct group keyword tokens, ties by passage index, fitting whole passages
to the remaining budget. Return them in document order. PDF anchors use the first
passage because PDF extraction has no heading metadata.

Mandatory first/heading passages can alone exceed the target; they are retained
intact and no further passages are added. This honors structural retention but
is not a hard provider context bound. Keyword retrieval can miss facts. No text
is cut inside a passage. `truncated` indicates any omitted passage;
`passages_dropped` is the largest omitted count in any group, and
passages_dropped_by_group records all five counts. A false truncated flag does
not imply a complete or accurate extraction.

Trusted system/task strings contain no interpolated page text. All page content,
including instruction-like strings, travels only as `(passage_id, text)` pairs in
untrusted_passages. Prompts require verbatim short quotes, explicit citations,
abstention/linked information, and the labeling guide's value normalization.
They use only the fictional Example Excellence Scholarship. Tests read gold
files without writing them and prohibit page-derived values, quotes and source
URLs in prompts; common schema vocabulary is necessarily shared.

## Manual local extraction

From the repository root, after configuring the LLM environment:

```sh
python scripts/extract_snapshot.py --slug fictional-award --snapshots-dir /private/snapshots
```

Exactly one `<slug>.html` or `<slug>.pdf` must exist. The script reads only that
file, never gold labels or the network fetcher, and never writes a snapshot or
label. It may call the configured LLM when manually run; read_only cache mode
avoids provider calls. It prints record JSON and a short presence summary, never
keys/headers. Its source URL is the local file URI and retrieved_on is the UTC
date of this local read, **not** a claim about the original website retrieval.
Applications needing original provenance must supply explicit Source metadata
to run_pipeline. The script was not run as part of implementation.

## Deliberate limits

This issue measures no accuracy and labels no real pages. Eleven synthetic page
layouts exercise contracts, not product quality. Boundary defenses do not claim
a hostile model obeys the prompt. Prompt registry
and experiment management remain #22; version tags here identify fixed v1 files.
No inference from country/year, currency conversion, OCR, link following,
eligibility decisions, character-edit quote matching, or new dependencies.

## Injection defenses and remaining risks

[Threat model 17](17-threat-model-injection.md) and [ADR 014](adr/014-prompt-injection-defenses.md)
describe shared escaped fencing, rendering-version cache invalidation, literal
URL provenance on each group's selected passages, and advisory suspicious_passages
on PipelineResult/manual script output. Rejected URLs use URL_NOT_ON_PAGE; valid
siblings survive. A URL must appear in cleaned text, not merely an href attribute.
Original passages and cleaner behavior are unchanged. The scan never filters data
or changes verification. False page content (including an obeyed fake deadline),
hidden text that survives cleaning, and real-model compliance remain residual
risks; live-provider adversarial evaluation using the reusable fixtures is deferred
to M3. The old claim that injected instructions cannot change any output is not
made; the owner-approved interpretation is recorded in issue #21's comment.

**Known limitation:** the cleaner keeps no link targets. An application_link or
linked_url that exists only as an href is rejected as `URL_NOT_ON_PAGE` because
it is absent from the passage text. Fixing this needs a cleaner change with a
CLEANER_VERSION bump and snapshot-drift review (derived hashes, offsets and
passage IDs may change even when raw HTML does not). This is out of scope here;
[M1 issue #81](https://github.com/KhuzaimaHassan/ScholarScope/issues/81) tracks it.
Application-link recall depends on that follow-up.
