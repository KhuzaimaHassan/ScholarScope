# Extractor v0: one prompt per field group

The baseline makes five `generate_structured` calls, in fixed order: identity
(program_name, institution, application_link, degree_levels), funding
(funding_coverage), documents (required_documents, recommenders), deadlines, and
conditions. Identity uses v2, funding v4, conditions v3, documents v2 and deadlines v2.
Provider retries and caching remain the LLM interface's responsibility; there is
no additional retry loop.
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

`convert.py` checks funding entries in order: **numeric provenance, item-term
provenance, then canonical domain validation**; entries have no URLs. Other items
retain numeric provenance, URL provenance, then domain validation. Field-level
linked_url metadata retains its URL guard before field domain validation.
First failure wins: reasons are never merged
and values are never repaired. Every accepted field, deadline and condition starts
at verification `not_checked`.
Conversion never promotes verification. Invalid fields/items and duplicate
deadlines are reported in `rejected_items` with group, original index (or field
name), reason and raw item; valid siblings remain. Do not publish rejected raw
items without reviewing their untrusted contents. Structural wire failures are
retried by the client and can fail the group; partial acceptance applies to
domain validation after successful wire parsing, not malformed JSON.

### Numeric provenance

[ADR 021](adr/021-numeric-provenance-guard.md) requires GPA value/scale, language
option min_overall/min_subscore, and funding amount/amount_max to occur numerically
in the item's own evidence quotes. Funding entries share all quotes of their
funding_coverage field; condition quotes are never borrowed from siblings or
uncited passages. Null optional amounts/subscores require no match. Reject the
offending condition or funding entry with `NUMBER_NOT_IN_QUOTE:<field>` (such as
min_overall), original index and raw item; keep valid siblings. Rejected numeric
values remain only in raw_item, not record values or diagnostic notes. Funding
indexes refer to original funding_coverage.value entries before filtering.

Tokens match `\d[\d.,]*`; strip trailing periods/commas. Parse both comma
interpretations: remove commas as thousands separators, or treat commas as the
decimal point and remove period grouping. Also, tokens matching
`^\d{1,3}(\.\d{3})+(,\d+)?$` admit dot-thousands: remove dots and convert any comma
to a decimal point. Thus `2.771` allows both 2.771 and 2771, `2.771,50` allows
2771.5 without rounding to 2771, while `1.5` and `3.85` retain decimal meanings.
Existing `1,234.56` and comma-grouped formats remain supported; terminal currency
punctuation adds no digit. Use exact finite-float equality, without tolerance or
substring matching. Number words and other notations remain out of scope. These
are presence checks, not units, role, association or support proof; the unchanged
verifier still checks quote presence separately.

Domain language-option min_overall must be > 0; optional min_subscore must also
be > 0. A zero missing from the quote fails numeric provenance first; a quoted
zero reaches domain validation and fails with its existing reason format.
Provider wire schemas remain permissive. The fictional gold example still passes
the gold validator and canonical parser. The standalone gold validator remains
structural; canonical parsing now rejects nonpositive language scores without
changing any label or the gold JSON schema.

Known gaps: number words (including spelled-out decimals) are not parsed; guarded
values supported only by words will be rejected. Recommender counts, dates,
times and age conditions are outside this guard. Unrelated numbers in the same
quote can match a claim; locale ambiguity is not resolved.

### Funding item-term provenance

[ADR 022](adr/022-funding-item-term-guard.md) adds the English-only constant
`FUNDING_ITEM_TERMS` in extraction/guards.py, covering every non-other item in the
canonical FundingCoverage.item Literal:

| Item | Terms |
|---|---|
| tuition | tuition, fee |
| stipend | stipend, allowance, living, maintenance, salary, monthly |
| travel | travel, flight, airfare, ticket, transport |
| insurance | insurance |
| housing | housing, accommodation, dormitor, lodging, rent, room and board |
| visa | visa |

For each non-other entry, at least one listed term must match a field evidence
quote with case-insensitive `\bterm` word-start matching on the original quote.
For example, rent matches rental but not current; phrases retain their literal
spacing. No fuzzy matching, translation or quote normalization is used, and terms
are not borrowed from uncited text or joined across quotes. All quotes of the
funding field are eligible. The generic words residence, stay, permit and grant
are deliberately excluded. Item other bypasses only this term guard, not numeric
or domain checks.

Missing terms reject the entry as `ITEM_TERM_NOT_IN_QUOTE:<item>`, preserving its
original index/raw item and valid siblings without reclassification. When all
entries fail, conversion leaves the field absent with its EXTRACTION_REJECTED
note; group orchestration retains that note alongside the required
EXTRACTION_FAILED marker and reports the group failed. Raw items remain opt-in
console data under --show-rejected. Non-English quotes without English lexicon
terms will have non-other funding entries rejected and reported, not silently
dropped; other remains available. English loanwords/prefixes can also cause
matches. This controls categories only: a matching term anywhere in the shared
quotes does not prove support, amount/period/currency correctness, or that a cost
is actually funded. The independent quote verifier still runs.

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

`failure_details` maps every failed group to category, nullable `http_status` and
nullable `message`. Categories are rate_limited, server_error, bad_request,
timeout, schema_rejected and other. Invalid/over-complex provider schemas are
schema_rejected, with no fallback. The message is only a structured provider
`error.message` on HTTP 4xx/5xx or provider-reported errors, sanitized under
[ADR 020](adr/020-ephemeral-provider-failure-details.md): redact credentials/tokens
and URL queries, withhold any 20-character request-text echo, collapse whitespace,
then cap at 300 characters. Missing messages remain null. Local failures expose
no provider message. Messages live only in memory and script console output,
never records, cache, snapshots, reports or logs; failure notes are unchanged.
`group_latency_seconds` measures wall time around each group call (including
client retries/cache lookup); skipped groups use zero. `group_usage` contains
each returned nullable input/output token count, not aggregate retry billing;
cached usage describes the original response, not new tokens spent.

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
Prompts use fictional examples only. Tests read gold files without writing
them and prohibit page-derived values, quotes and source
URLs in prompts; common schema vocabulary is necessarily shared.

funding-v4 retains v2's `other` for costs outside named categories and preserves
exact wording in the note, rather than selecting the nearest category.
documents-v2 splits distinct documents into separate entries using source wording,
even when listed in a single sentence, without inventing documents. conditions-v3
uses kind `other` and the requirement sentence when proficiency is required
without a named test or score. Empty-options language conditions remain domain
validation errors. Each changed task/version invalidates the corresponding cache
key; historical prompt files remain available as baselines.

deadlines-v2 defines the six existing enum types by the required action: whole
application submission/completion uses application, document-only completion
uses document, and recommendations use recommender; scholarship is reserved for
award-specific milestones, never the page's subject. Three fictional 2034-2035
examples illustrate submission, whole-application completeness and recommender
cutoffs. The owner authorized these explanations from the action rule because
the schema/guide list enum names without per-type prose. deadlines-v1 remains a
historical baseline; task/version changes invalidate its cache entries. Offline
FakeClient tests verify wiring and cache identity, not real-model type choices.

identity-v2 separates the offered programme/award level from applicant prerequisites.
funding-v4 retains v3's amount semantics: what the funder pays/grants, leaving a reduced fee
still paid by the student as null amount with its sentence in the note, and uses
period only when explicitly present in the quote. conditions-v3 separates degrees
held/expected by applicants from the funded programme, reserves residency for
place-of-residence/stay requirements, uses other for tuition classification/visa
rules, and avoids conditions restating the same quote. It prominently repeats the
general language-requirement other-kind rule with a fictional example.
funding-v4 additionally requires the quote to name each selected cost category,
uses other for unnamed categories, and asks for the shortest cost-naming wording
in each item's note rather than repeating an entire sentence across items.
Prompt effects cannot be validated offline: these are instructions checked by
manual real runs. Synthetic tests validate versions, cache invalidation and local
contracts, not model compliance or accuracy; no live run was performed for this PR.

## Manual local extraction

From the repository root, after configuring the LLM environment:

```sh
python scripts/extract_snapshot.py --slug fictional-award --snapshots-dir /private/snapshots --source-url https://example.invalid/award
```

Exactly one `<slug>.html` or `<slug>.pdf` must exist. The script reads only that
file, never gold labels or the network fetcher, and never writes a snapshot or
label. It may call the configured LLM when manually run; read_only cache mode
avoids provider calls. It prints record JSON and a summary with verification,
failed_groups/failure_details, group_status, group_latency_seconds, group_usage,
truncated and passages_dropped. Rejections include group, index and reason;
`--show-rejected` additionally includes the private raw item (off by default).
Do not persist/redirect diagnostics: messages are console-only, and raw rejected
items may contain page text. It never prints keys/headers.

Without `--source-url`, its source URL is the local file URI and relative hrefs
cannot resolve against an HTTP origin. With the flag, require HTTP(S) with a host
and no embedded credentials; use it as SourceInfo.url and the cleaner's explicit
base for relative targets. The cleaner preserves HTTP(S)
`fetch_result.final_url or fetch_result.url` as its base, using an HTTP(S)
`source.url` only when that fetch URL is non-HTTP(S).
`source_url_user_supplied: true` records this user assertion, not verified
retrieval provenance. No URL is fetched and the literal
URL guard is unchanged. In both cases retrieved_on is the UTC
date of this local read, **not** a claim about the original website retrieval.
Applications needing original provenance must supply explicit Source metadata
to run_pipeline. The implementation tests use only fictional local files and
mocked/scripted providers.

## First real run

Owner-reported observations from one manual run (not accuracy measurements):

- The deadline group reported provider_error without diagnostic detail.
- A general language-proficiency condition with empty options was rejected.
- An unlisted administrative cost was assigned to a named funding category.
- Several required documents were returned as one compound list entry.
- The application link was absent; using a file URI as the relative-link base
  is a possible cause, not a measured attribution.

These observations motivate the changes above. No source-page wording is copied
here, no accuracy claim is made, and no live run was performed for these fixes.

## Second real run

Owner-reported observations from a second manual run, not accuracy measurements:

- A language condition contained a fabricated min_overall of 0.0.
- A tuition amount described a remaining student fee rather than a funder payment.
- Offered degree levels and applicant prerequisites were mixed.
- Condition kinds were misused for programme, residence and fee/visa concepts.
- Deadline-type choices require review; no deterministic deadline-type fix is
  implemented in this change.

These observations motivate the guard and prompt revisions. No real-page wording
is reproduced, and passing local checks makes no accuracy claim.

## Deliberate limits

This issue measures no accuracy and labels no real pages. Eleven synthetic page
layouts exercise contracts, not product quality. Boundary defenses do not claim
a hostile model obeys the prompt. Prompt registry
and experiment management remain #22; version tags here identify fixed prompt files.
No inference from country/year, currency conversion, OCR, link following,
eligibility decisions, character-edit quote matching, or new dependencies.

## Injection defenses and remaining risks

[Threat model 17](17-threat-model-injection.md) and [ADR 014](adr/014-prompt-injection-defenses.md)
describe shared escaped fencing, rendering-version cache invalidation, literal
URL provenance on each group's selected passages, and advisory suspicious_passages
on PipelineResult/manual script output. Rejected URLs use URL_NOT_ON_PAGE; valid
siblings survive. Cleaner v2 appends retained HTTP(S) href targets as synthetic
anchor-located text, so the unchanged provenance guard can accept those targets.
The scan never filters data
or changes verification. False page content (including an obeyed fake deadline),
hidden text that survives cleaning, and real-model compliance remain residual
risks; live-provider adversarial evaluation using the reusable fixtures is deferred
to M3. The old claim that injected instructions cannot change any output is not
made; the owner-approved interpretation is recorded in issue #21's comment.

**Residual link cases:** targets in excluded/empty anchors, unsupported schemes,
relative targets without enabled/usable base context, and URLs in omitted passages
are still absent from the group's text and rejected as URL_NOT_ON_PAGE. Scheme-less
labels suppress duplicate suffixes; a model-produced absolute URL absent from that
text is still rejected, not repaired. URL matching and scan rules are unchanged.
Cleaner v2 changes derived text/maps and requires deliberate baseline review even
when raw bytes are identical. No labels/snapshots were migrated. Existing prompts
already ask for the page's actual target; identity-v2 retains that URL requirement.
