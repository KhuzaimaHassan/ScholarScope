## Provenance

The Radboud label is AI-assisted, authorized by the owner on 2026-11-10, and
**pending independent human review**. The entries dated 2026-11-10 below are
source-based decisions, not an independent human label or a measured extraction
result. The label records
`codex-ai-assisted` as its author and agent elapsed time; human review remains
necessary before using it as an independent quality baseline.

On 2026-11-16 the owner authorized Codex to perform the requested review on
their behalf. Pass 2 is also signed `codex-ai-assisted`; it is an AI-assisted
source review, not a human sign-off or the blind relabel in guide 07. It checked
the live source and read the existing local report's source-text section after
the browser blocked its `file://` URL. Model predictions were not treated as
ground truth. The frozen HTML hash and all retained evidence quotes were
checked against the original snapshot; neither snapshot file was changed.
Original retrieval metadata stays fixed despite a changed allocation total on
the live page. The initial pass's 4.62 agent minutes remain historical; the
label's `minutes_spent` now measures this review only and must not enter metrics.
The review timer ran from 05:59:26 to 06:04:19 UTC on 2026-11-16: 293 seconds,
recorded as 4.88 agent minutes. Validation and the subsequent provider rerun are
outside this measurement; no human labor time or independent review is claimed.

2026-11-16: Label revised after viewing model output: the pass-2 changes to recommender type, formal-admission kind, faculty list and recommendation line were made after the owner and the AI-assisted reviewer had seen a comparison against the extractor's output. Radboud is a development label; its scores must not be presented as an independent baseline.

| date | slot | situation | decision | rule it should become |
|---|---|---|---|---|
| 2026-11-10 | Netherlands 3 | Frozen source metadata versus today's labeling session | Preserve the original retrieval date and verified original-file hash; set today's labeling date separately. Keep page state unknown without an explicit availability statement. | Label the frozen source and separate retrieval, labeling and availability provenance. |
| 2026-11-10 | Netherlands 3 | Initial submission and later completion in a combined admission/award workflow | Classify both actionable cutoffs as `application`, with distinct submission/completion labels. Completion includes the whole application, not only documents; do not use the page's scholarship category as the deadline type. | Deadline type follows the required action. Retain distinct stages without manufacturing another cutoff. |
| 2026-11-10 | Netherlands 3 | Explicit CET times and an approximate result-notification window | Map CET to `UTC+01:00`; omit the notification window from applicant-action deadlines and do not invent an exact day. | Normalize only an explicit timezone; separate applicant cutoffs from result announcements. |
| 2026-11-10 | Netherlands 3 | A reduced student fee appears alongside covered costs | Record tuition coverage with null award amount; retain the residual-fee wording and its provisional status in the label. | A student payment is not a funder payment or an inferred grant amount. |
| 2026-11-10 | Netherlands 3 | Covered administrative and insurance costs, with living costs excluded | Use `visa`, `other` for the unmatched administrative cost, and `insurance`; do not invent housing or a stipend. | Match cost categories literally; retain explicit exclusions and use `other` for unnamed categories. |
| 2026-11-10 | Netherlands 3 | Award duration is stated separately from individual cost payments | Preserve duration evidence and explanatory notes but leave per-cost payment periods null. | Award duration alone does not establish payment frequency for every cost. |
| 2026-11-10 | Netherlands 3 | Two requested document types include multiple reference letters | Separate the two document types; record letter count separately. Academic referee wording is a preference. | Distinguish document types, copy counts and optional referee preferences. |
| 2026-11-10 | Netherlands 3 | A recommended proof-submission time and a selection-factor document are also mentioned | Do not add them as mandatory uploads to the additional-document list. Preserve the timing recommendation as `other`, `required: false`. | Mentions, preferences and selection factors do not by themselves establish mandatory document requirements. |
| 2026-11-10 | Netherlands 3 | Application text links to an admission-procedure landing page | Use the explicit application anchor target as `application_link`, noting it is a procedure page, not an invented direct portal endpoint. Do not follow it. | Record explicit workflow links and distinguish them from direct submission endpoints. |
| 2026-11-10 | Netherlands 3 | Funded programme level differs from the prerequisite degree | Keep the funded level in `degree_levels`; use `degree_held` only for the prior/to-be-obtained qualification. Preserve separate education-history restrictions and exceptions as `other`. | Separate award level, prerequisite degree and education geography. |
| 2026-11-10 | Netherlands 3 | Language proficiency is required without named tests or numerical thresholds | Use `other` with the source sentence; create neither language-test options nor numerical placeholders. Qualitative academic selection factors do not imply a GPA threshold. | Do not infer numerical thresholds or invent tests from general proficiency requirements. |
| 2026-11-10 | Netherlands 3 | Passport group, fee classification and visa compliance are different requirements | Keep passport-group wording under `nationality_allowed`; use `other` for fee classification and visa compliance. No country expansion or residency inference. | Preserve the source distinctions; current residence cannot be inferred from these requirements. |
| 2026-11-10 | Netherlands 3 | Formal admission, full-time enrollment, programme/faculty scope and later renewal have different applicability | Keep admission and enrollment as distinct states; retain programme/faculty scope. Limit renewal requirements to the relevant recipients and year. | Preserve applicable groups and stages rather than turning conditional renewal into an entry requirement. |
| 2026-11-16 | Netherlands 3 | Referee category included a preference qualifier | Set recommender type to `academic`; keep the preference and non-exclusive nature in notes. Both the wire and domain schemas currently accept free-text types; there is no closed type enum to repair. | Store the category separately from a preference qualifier; a preference must not become an exclusive requirement. |
| 2026-11-16 | Netherlands 3 | Tuition coverage has no stated award amount, while the student-paid fee has a currency | Keep tuition amount, amount_max and currency null. For this label, set currency only alongside an explicitly stated award amount or maximum; the same rule leaves all other non-quantified items null. | A residual student payment does not establish the award amount or its currency. This is a labeling decision, not a schema or prompt change. |
| 2026-11-16 | Netherlands 3 | Formal admission was encoded as enrollment status | Change that condition to `other`, retaining its exact value/evidence. Keep actual full-time enrollment as `enrollment_status`. This supersedes the admission-kind decision in pass 1. | An offer/formal admission does not establish enrollment; retain admission as a separate requirement without a dedicated admission kind. |
| 2026-11-16 | Netherlands 3 | Faculty metadata appeared as a mandatory condition | Remove the faculty-list entry. Retain the explicit programme-eligibility restriction and the conditional renewal requirement. This supersedes pass 1's faculty-scope inclusion. | Descriptive scheme metadata is not an applicant requirement. |
| 2026-11-16 | Netherlands 3 | Optional timing advice appeared as a condition with required false | Remove the recommendation entry; retain the actual application-completion deadline. This supersedes pass 1's optional-condition inclusion. | Recommendations are omitted from requirements; required false represents an explicit non-requirement rather than optional advice. |
| 2026-11-16 | Netherlands 3 | Application submission and later whole-application completeness were reviewed again | Keep both deadline types as `application` with their distinct actions, dates and explicit timezone. No document-only cutoff was added. | Type follows the required action; whole-application completeness remains application. |
| 2026-11-16 | Netherlands 3 | Live allocation metadata differs from the frozen source | Preserve the frozen source date/hash and the supported retained quotes; no allocation count is modeled by this label. Record today's review date separately. | Reviewing a live page must not silently replace frozen-source provenance or relabel unrelated facts. |
