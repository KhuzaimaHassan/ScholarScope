# Prompt-injection threat model

This issue implements boundary checks, not a claim that an LLM obeys trusted
instructions. The owner-approved criterion is recorded in
[issue #21's clarification](https://github.com/KhuzaimaHassan/ScholarScope/issues/21#issuecomment-6437439193):

> Injected instructions in test pages cannot change the output schema, set verification status, introduce a URL absent from the page, or alter the trusted prompt. Whether a real model obeys injected content is measured later in the M3 harness (adversarial pages, live provider).

Here URL provenance applies to the structured application_link value and every
field-level/deadline-set linked_url. Arbitrary strings such as notes remain
untrusted data; displaying them must never trigger link navigation, image loads,
tool execution or rendering of active Markdown/HTML automatically.

## Assets and trust boundaries

| Asset/boundary | Trusted side | Untrusted side and treatment |
|---|---|---|
| Extraction policy and schema | Code-owned system/task, fixed wire models and canonical validators | Page text and model output cannot edit these objects |
| Passage identities | Segmenter-generated IDs supplied by code | Text imitating IDs/headers is escaped data, never a new structural passage |
| Evidence state | Conversion starts not_checked; deterministic verifier alone assigns verified/unverified | Model-claimed verification is ignored; forged citations fail presence checks |
| Navigable result URLs | Literal provenance guard over each group's selected passages | Reject application_link/linked_url not present verbatim; do not fetch, repair or infer |
| Original source text | Immutable segmented text and offsets used by verifier | Escape only the provider message, never the source document |
| Keys and private data | Credentials stay in adapter headers; private snapshots/cache remain private | No tools, browsing or image loading are exposed to extraction; do not interpret model text as actions |

## Request fencing and cache identity

The shared renderer in llm/base.py wraps one JSON array inside the exact fences
`[BEGIN UNTRUSTED DATA V3]` and `[END UNTRUSTED DATA V3]`. Only renderer-owned JSON
record structure and passage_id properties identify passages. Strings use standard
JSON (`ensure_ascii=False`), then escape only square brackets, angle brackets,
vertical bars and backticks as Unicode escapes. URLs, dates, colons/commas and
non-ASCII text remain readable. JSON still escapes quotes, backslashes and
newlines normally; source header-like text stays inside a quoted string rather
than creating a separate passage, system or task line. Fence/tag building blocks
cannot appear raw inside source strings. Decoding recovers the original IDs/text
exactly. This does not erase the meaning of instructions after a model reads data.

Gemini, Groq and Ollama all use this single renderer. Their native system field
remains the trusted request.system, and the original request.task is not edited.
`RENDERING_VERSION="3"` is part of the cache key, so older rendering results are
not replayed. Any rendering behavior change must bump this version. Quotes are
copied from the decoded strings and verified against the original document,
never against the escaped provider-message representation.

The normal-prose regression fixture measures 5,162 rendered characters for 5,000
source characters (1.0324x, including fences and JSON record overhead). This is
an example, not a general bound for delimiter-heavy or control-heavy payloads.

## URL provenance and advisory findings

After local canonical validation, application_link and field-level linked_url
must occur verbatim within one passage sent to that field's group. The deadline
set's linked_url is checked against the deadline group's passages before metadata
is retained. An omitted passage, href-only attribute, relative/resolved variant,
case change or percent-decoded reconstruction cannot supply a URL. A failed item
is recorded with reason exactly `URL_NOT_ON_PAGE`, original raw input and index;
valid sibling claims/deadlines survive. No URL is repaired, followed or fetched.
This intentionally rejects some legitimate links not visible in cleaned text.

**Known limitation:** the cleaner keeps no link targets. An application_link or
linked_url present only as an href attribute is rejected as `URL_NOT_ON_PAGE`.
Fixing this requires a cleaner change, a CLEANER_VERSION bump and review of
snapshot drift/derived hashes, offsets and passage IDs. It is out of scope here;
[M1 issue #81](https://github.com/KhuzaimaHassan/ScholarScope/issues/81) tracks it.
Application-link recall depends on preserving those source targets.

The scan reports SuspiciousPassage(passage_id, reasons) in document order, with
fixed-order reason codes: instruction_override, fake_role_tag, requested_output,
requested_state, exfiltration, passage_header. It scans all segmented passages,
including those later omitted from a group's budget. Findings appear on
PipelineResult.suspicious_passages and in the manual extract_snapshot summary.
**The scan is advisory and bypassable:** it never removes/rewrites passages,
changes claims, or changes verification. Obfuscation, other languages, split
instructions and novel patterns evade it; benign policy text may trigger it.

## Hidden-text audit: current behavior, unchanged

These observations are regression-tested with fictional sentinel text, including
checking the final passages. They are not a computed-browser visibility guarantee.
No cleaner rule or version changes in this PR.

| HTML case | Sentinel reaches passages? | Existing behavior |
|---|---|---|
| Inline display:none | No | Excluded by static inline-style filtering |
| Inline visibility:hidden | No | Excluded by static inline-style filtering |
| aria-hidden="true" | No | Excluded by attribute filtering |
| HTML comment | No | Comment nodes excluded |
| Tiny font-size:1px | **Yes** | Font size is not evaluated |
| Zero font-size:0 | **Yes** | Font size is not evaluated |
| width:0;height:0;overflow:hidden | **Yes** | Dimensions/clipping are not evaluated |
| Stylesheet-only .fictional-hidden {display:none} | **Yes** | Stylesheet cascade is not evaluated |

The decision here is to preserve existing cleaner behavior and expose the gap.
Tiny/zero-size or stylesheet-hidden instructions can reach the provider and can
even have their literal quotes verified. The advisory scan is not a hidden-text
detector. Changing visibility handling needs a separate explicit policy and
cleaner version change, not a silent filter in this issue.

## Residual risks and deferred evaluation

| Risk | What the defenses do | What remains |
|---|---|---|
| Fence/role/header forgery | Escaped JSON prevents structural delimiter/record injection | A model can still follow the decoded words |
| Schema or verification override | Fixed schemas, local validation, conversion reset and mandatory verifier | A schema-valid wrong value with real evidence can survive |
| URL redirection/exfiltration | Reject URLs absent from selected source text in structured URL fields | A hostile URL actually on the page passes; provenance is not safety/authority; other strings need inert display |
| False factual page content | Verifier checks quote presence only (ADR 003/012) | Genuine false source content can be verified; support, authority and truth need separate review |
| Hidden instructions | Static cleaner excludes the four audited hiding mechanisms above | Tiny/zero-size and stylesheet-hidden cases remain in passages |
| Advisory detection bypass | Deterministic findings help audit/debugging | False positives/negatives; no security decision can depend on a clean scan |
| Context size | Readable JSON with only six additional escaped characters keeps inflation small for normal prose | Fences/JSON add overhead; delimiter-heavy text expands more, and the soft character target is not a provider token limit |
| **Deferred to M3** | Reusable fictional adversarial fixtures committed for offline boundary tests | **Live-provider adversarial evaluation using these same fixtures**, comparing real-model compliance in the M3 harness; not performed here |

The obeyed-fake-deadline test **documents a residual risk, not a defended case**.
Its page instruction contains a fictional false deadline sentence. The scripted
model quotes that sentence with a real passage ID; conversion resets verification
to not_checked, but the presence-only verifier correctly marks it verified.
The deadline/value is kept and currently satisfies usable_for_logic. This is not
proof that the deadline is true, supported by an authoritative source, or safe to
act on. The advisory warning does not override the verifier or rule engine.

## Reusable adversarial fixtures and test limits

`tests/fixtures/injection_cases.json` has eight fictional payloads with stable
IDs and expected heuristic reasons: instruction override, fake closing fence/
system section, forged passage header, verification override, alternate URL,
Markdown-image exfiltration, fake deadline, and system-prompt disclosure. Reuse
the same payload strings in M3: HTML-escape text into a pre element under a
fictional heading, then use the normal cleaner/segmenter pipeline. Do not put
payloads into trusted prompts. The test recipe is fixture_html in test_injection.

FakeClient callbacks deliberately obey attacks to exercise downstream checks.
MockTransport checks each adapter's rendered request; socket/DNS attempts fail
the new tests. These are deterministic software-boundary tests, **not evidence
of real-model injection resistance**. No live sites/providers, real keys, gold
labels, snapshots, accuracy evaluation, or manual extraction run were used.
