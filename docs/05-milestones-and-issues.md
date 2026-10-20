# 05 — GitHub Milestones and Issues Plan

**Status:** Draft v0.2 (reviewed; edits applied). One milestone per phase, one tracking issue per milestone (checklist of its child issues).
Labels to create: `type:docs`, `type:feature`, `type:eval`, `type:infra`, `type:bug`, `good first issue`, `delegate:ai`, `delegate:human`, `delegate:pair`, `risk`, `blocked`.

Definition of done for any issue: acceptance criteria met, tests added, docs updated, eval subset not regressed, PR reviewed by you.

---

## M0 — Foundations and docs
**Goal:** Repo is ready, docs reviewed, decisions recorded.
Tracking issue: *[M0] Foundations and docs*

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| Create repo, add MIT license, README skeleton | infra | human | MIT `LICENSE` committed; README has problem + roadmap |
| Add docs 01–05 to `/docs` | docs | human | Reviewed and edited by you |
| Write ADR 001–007 plus ADR 008 (unverified fields retained, excluded from logic) and ADR 009 (rule provenance) | docs | pair | One file per ADR with context/decision/consequences |
| Set up labels, milestones, issue + PR templates (incl. AI-assistance field) | infra | ai | Templates render correctly |
| CI skeleton: lint, test, type-check | infra | ai | Green on empty project |
| Register domain (name decided: ScholarScope) | infra | human | Domain registered or consciously deferred |
| Review terms of use for the nine source families | risk | human | Outcome recorded per family in `docs/source-terms.md`; snapshot policy decided |

## M1 — Fetch, clean, segment
**Goal:** URL in → clean passages with stable IDs out.
**Runs in parallel with M3 labeling.** Both start after M0; neither blocks the other until M2.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| Fetcher with robots.txt, rate limit, caching by content hash | feature | pair | Respects robots; cache hit avoids refetch; tests with mocked HTTP |
| Playwright fallback for JS pages | feature | ai | Used only when static fetch yields too little text |
| HTML main-content cleaner | feature | ai | Works on 10 sample pages; keeps offsets |
| PDF text extraction | feature | ai | Handles text PDFs; scanned PDFs flagged as unsupported |
| Segmenter with stable passage IDs and offsets | feature | human | Same input → same IDs; offset round-trip test |
| Snapshot store for eval | eval | ai | Frozen HTML/PDF saved per program, private by default; public repo holds only hashes, labels, short quotes, and a re-fetch script unless a source's terms allow more |

## M2 — Evidence-linked extraction
**Goal:** Typed Requirement Records with verified evidence.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| Pydantic schema for Requirement Record | feature | human | Every field has value, evidence list (quote, passage_id, locator), status (present/absent/ambiguous/in_linked_document), verification (not_checked/verified/unverified), linked_url, notes, and advisory confidence; usable_for_logic only when present and verified (ADR 010) |
| Deadline model: type, cycle/year, timezone, rolling flag, multiple per program | feature | human | Schema + tests for multiple deadlines, unknown timezone, and rolling programs |
| Provider-agnostic LLM interface (Gemini, Groq, Ollama) | feature | pair | Swap by config; retries and caching |
| Extractor v0 (single prompt baseline) | feature | pair | Produces valid records on 10 pages |
| Evidence verifier (exact + normalized fuzzy) | feature | human | Unit tests incl. adversarial quotes; failures are **retained and marked `unverified`**, never dropped; verifier checks quote presence only |
| Prompt-injection hardening of extraction step | risk | human | Test pages with injected instructions do not change output |
| Prompt/version registry | infra | ai | Each extraction stores model + prompt version |

## M3 — Gold set and evaluation harness
**Goal:** Reproducible accuracy numbers.
**Labeling runs in parallel with M1.** The labeling guide and first labels must exist before M2 tuning begins.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| Labeling guide (field definitions, edge cases) | docs | human | Rules for ambiguity written before labeling |
| Choose the 36 programs: nine families, four each (DAAD-, Chevening-, Fulbright-, GKS-, CSC-type, Erasmus Mundus, Netherlands, Japan, Italy) | eval | human | Program list with URLs and layout type recorded **before** labeling starts; each family mixes layouts |
| Label shortlist families first (CSC, Erasmus Mundus, Netherlands, Japan, Italy: 20 programs) with quotes | eval | human | Stored in `eval/gold/`; snapshots frozen |
| Label remaining families (DAAD, Chevening, Fulbright, GKS: 16 programs) with quotes | eval | human | Stored in `eval/gold/`; snapshots frozen; total 36 programs, mix of HTML, PDF, JS-heavy, multi-page |
| Human audit of evidence support on 50 fields | eval | human | Support rate recorded separately from evidence presence |
| Second-pass labeling on 10 programs | eval | human | Agreement rate recorded |
| Harness computing all metrics in `03` | eval | pair | One command outputs a report |
| Baseline run and results table | eval | human | Numbers committed with date and versions |
| CI regression gate on subset | infra | ai | PR fails if dangerous-error rate regresses or evidence presence drops below 100% |
| Start `docs/error-analysis.md` | docs | human | First 5 failure classes documented |

## M4 — Eligibility engine and checklist
**Goal:** Deterministic verdicts and dated plans.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| Profile schema (degree, GPA + scale, nationality, language scores, documents) | feature | human | Validated; GPA scale normalization |
| Rule engine: min GPA, degree level, nationality, age, experience, language tests | feature | human | Uses verified fields only; missing or `unverified` data → `unclear`; confidence never used; 90%+ unit coverage |
| Rule provenance registry (ID, version, description, rationale, source note, tests link) | feature | human | Every verdict cites rule ID and version; each rule has provenance filled in |
| Verdict explanations with source quotes | feature | pair | Each reason links to evidence |
| 5 synthetic profiles per gold program with hand-labeled verdicts | eval | human | Used for eligibility agreement metric |
| Checklist generator with deadline buffers | feature | ai | Uses verified deadlines only; handles multiple deadlines, rolling programs, and unknown timezone (warn, no buffer); tested |
| Missing-document detector | feature | ai | Compares required vs. profile documents |

## M5 — API and UI
**Goal:** Usable end-to-end product.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| FastAPI endpoints + async jobs | feature | pair | OpenAPI docs; job status polling |
| PostgreSQL schema and migrations | infra | pair | Migrations reproducible |
| Next.js: paste URL → result page | feature | ai | Works on mobile width |
| Evidence side-panel with click-to-highlight source | feature | pair | Clicking a field scrolls to and highlights the passage |
| Compare view (3+ programs) | feature | ai | Sortable by deadline and eligibility |
| "Last checked" + stale-data banner | feature | ai | Shown on every record |
| Delete-my-data endpoint | risk | human | Profile removable; verified by test |

## M6 — Deploy and polish
**Goal:** Public demo anyone can try.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| Dockerize API/worker | infra | ai | One-command local run |
| Deploy frontend and backend (free tiers) | infra | pair | Public URL; secrets via env |
| Pre-load 20 example programs | feature | human | Demo works without an API key |
| README: GIF, architecture diagram, results table, limitations | docs | human | Numbers match latest eval run |
| Rate limiting and abuse protection on demo | risk | pair | Documented limits |
| Short demo video / write-up | docs | human | Linked from README and portfolio |

## M7 — Open-source readiness
**Goal:** Others can contribute.

| Issue | Type | Delegation | Acceptance criteria |
|---|---|---|---|
| `SiteParser` plugin interface + docs | feature | human | Example parser included |
| CONTRIBUTING.md, code of conduct, issue templates | docs | ai | Reviewed by you |
| 10 `good first issue`s (new parser, new gold entries, bug fixes) | docs | human | Each with clear acceptance criteria |
| Takedown/contact policy for site owners | risk | human | Linked in README |
| v1.0 release notes | docs | human | Changelog and known limitations |

---

## Suggested order and flow

```
M0 ──┬──► M1  (fetch, clean, segment)        ──┐
     │                                         ├──► M2 (extraction) ──► M3 baseline ──► M4 ──► M5 ──► M6 ──► M7
     └──► M3a (labeling guide + gold set)    ──┘
```

M1 and M3 labeling are **explicitly parallel** after M0. M2 tuning starts only when M1 is done and the labeling guide plus first labeled programs exist. The M3 baseline run happens after M2's v0 extractor.
Gate between milestones: tracking issue checklist complete and eval numbers recorded.

## Immediate next actions

1. Run `scripts/create_issues.py --dry-run`, review the output, then run it against the new repo.
2. Confirm the five gold-set families against your real application shortlist.
3. Register the domain (or defer on purpose) and review source terms of use.
