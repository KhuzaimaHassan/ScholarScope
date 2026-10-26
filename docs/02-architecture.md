# 02 — Architecture

**Status:** Draft v0.2 (reviewed; edits applied)

## 1. Design principles

1. **Evidence or abstain.** A field is shown as `verified` only if every quote is found in its cited passage or a contiguous match starting/ending there across adjacent passages (ADR 012). A field that fails this check is **retained but marked `unverified`**: it stays visible with a "check official page" notice and is **excluded from eligibility and checklist logic**.
2. **LLMs extract; code decides.** Eligibility and date logic are deterministic and unit-tested. The LLM never produces the final verdict. **LLM confidence is advisory only** (display and triage) and never affects eligibility or checklist output.
3. **Measure everything.** Every pipeline change is scored against the gold set in CI.
4. **Free-tier friendly.** Must run on free LLM tiers and a free host; model provider is swappable.
5. **Pluggable sources.** A generic extractor works everywhere; site-specific parsers override it where they are better.

## 2. Pipeline

```
URL ──► Fetcher ──► Cleaner ──► Segmenter ──► Extractor ──► Evidence Verifier ──► Requirement Record
        (httpx,     (main       (passages     (LLM,          (exact/normalized       │
        Playwright  content,    with stable   structured     of quote in source;     ▼
        fallback,   PDF text)   IDs + offsets) output,       fail=unverified)     Eligibility Engine ──► Checklist Generator
        robots.txt)                          Pydantic)                          (rules, profile)        (dates, missing docs)
```

### Components

| Component | Responsibility | Notes |
|---|---|---|
| **Fetcher** | Download page/PDF, respect robots.txt, rate limit, cache with content hash | httpx first; Playwright only when JS rendering is required |
| **Cleaner** | Strip navigation/boilerplate, extract main text (static HTML via BeautifulSoup with lxml; PDF text extraction is separate) | [HTML cleaner contract](08-html-cleaner.md): preserve headings and map text spans to original DOM nodes |
| **PDF text extraction** | Extract per-page text with pypdf layout mode; flag scanned/low-text and password-protected PDFs as unsupported | [PDF extraction contract](09-pdf-extraction.md): normalized page offsets and physical page locators; no OCR |
| **Segmenter** | Split into passages with stable IDs and character offsets | Evidence points to passage ID + span |
| **Extractor** | Five field-group prompts return provider-safe wire models, converted locally into a typed Requirement Record with `{status, verification, value, evidence[], linked_url, notes, confidence}` fields (ADR 013); evidence holds quote, passage ID and locator | Verification starts `not_checked`; only the deterministic verifier sets `verified`/`unverified` (ADR 010). `confidence` is advisory only. Consumers must inspect failed_groups/rejected_items before interpreting empty fields ([contract](16-extractor.md)) |
| **Evidence Verifier** | Confirms every quote **exists** in its cited passage or a contiguous match starting/ending there across adjacent passages (exact, then formatting normalization; ADR 012). Fails → claim becomes `unverified` (kept, not dropped) | Pure code, deterministic; no character-edit fuzzy matching. It proves *presence* only. Whether the quote actually *supports* the value is a separate, human-audited quality metric (see `03-evaluation-plan.md`) |
| **Eligibility Engine** | Rules over `(RequirementRecord, Profile)` → `eligible / not_eligible / unclear` + reasons. Uses **verified fields only**; any rule that needs an `unverified` or missing field yields `unclear` | Unit-tested; unknown data → `unclear`, never a guess. Every rule carries provenance (see section 3) |
| **Checklist Generator** | Dated tasks from deadline(s), missing documents, test dates | Buffers configurable |
| **Plugin interface** | `SiteParser` protocol: `can_handle(url)`, `parse(raw) -> RequirementRecord` | Enables contributions |
| **API** | FastAPI: `POST /programs` (URL), `GET /programs/{id}`, `POST /profile`, `GET /programs/{id}/eligibility` | Async job for slow fetches |
| **Storage** | PostgreSQL (programs, passages, extractions, profiles, runs) | Free-tier hosted Postgres |
| **Frontend** | Next.js: paste URL, result view with click-to-source highlight, checklist, compare view | Evidence side-panel is the signature UI |
| **Eval harness** | Runs pipeline over gold set, computes metrics, outputs report + CI gate | See `03-evaluation-plan.md` |

## 3. Data model (core)

```
Program(id, url, fetched_at, content_hash, institution, country, ...)
Passage(id, index, start, end, text_hash, section_heading, locator, source_refs, exceeds_max) -- text is a property slicing the shared immutable SegmentedDocument.text; no stored passage copy (ADR 011)
ExtractedField(id, program_id, name, value_json, evidence[{quote, passage_id, locator}], status[present|absent|ambiguous|in_linked_document], verification[not_checked|verified|unverified], linked_url, notes, confidence[advisory], model, prompt_version) -- usable_for_logic iff present and verified (ADR 010)
Deadline(id, program_id, extracted_field_id, type[application|document|recommender|scholarship|interview|other],
         cycle_year, date, time, timezone, rolling[bool], notes)   -- multiple per program
Profile(id, degree, field, gpa, gpa_scale, nationality, language_scores_json, documents_json)
EligibilityRule(id, name, version, description, rationale, source_note, tests_ref)   -- provenance per rule
Eligibility(id, program_id, profile_id, verdict, reasons_json[{rule_id, rule_version, field_id, quote_ref}])
```

### Deadline modeling

A program can have several deadlines. Each deadline stores its **type**, **cycle/year**, **timezone** (explicit, or `unknown` — never assumed), and a **rolling** flag (no fixed date). Dates with unknown timezone or ambiguous year are shown with a warning and excluded from buffer calculations until confirmed.

### Rule provenance

Each deterministic eligibility rule records: a stable ID and version, a plain-language description, the rationale for how it interprets the requirement (for example how a GPA scale is normalized), a note on where that interpretation comes from (program wording, common convention, or your own decision), and a link to its unit tests. Every verdict lists the `rule_id` and `rule_version` it used, so any result can be audited and reproduced.

## 4. Key decisions (ADR summaries — write one ADR file each in `docs/adr/`)

| ADR | Decision | Reason |
|---|---|---|
| 001 | Backend in FastAPI, frontend in Next.js | Existing skill; fast to ship |
| 002 | Structured outputs via Pydantic schemas | Typed, testable extraction |
| 003 | Evidence verification is code, not LLM | Removes self-grading bias |
| 004 | Deterministic eligibility engine | Auditable verdicts |
| 005 | Provider-agnostic LLM interface | Free-tier limits and model churn |
| 006 | Playwright only as fallback | Cost and speed |
| 007 | Public gold set in-repo | Reproducible claims |

## 5. Deployment (initial proposal)

- Frontend on Vercel free tier.
- API + worker in a Docker container on a free VM or container host (decide at M6 based on what is free then).
- GitHub Actions: lint, tests, eval regression gate, container build.
- Secrets via environment variables; no API keys in repo.

## 6. Technical risks specific to architecture

- JS-heavy sites → Playwright fallback adds latency; mitigated by cache.
- Long pages exceed context → passage-level retrieval before extraction.
- Rate-limited free LLM tiers → queue, retries, response caching keyed by the canonical provider/model, trusted messages, passage IDs/text, response schema, generation parameters and prompt version (see `15-llm-interface.md`).
