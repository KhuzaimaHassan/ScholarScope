# 04 — Risks and Diligence (the Diligence layer)

**Status:** Draft v0.2 (reviewed; edits applied)

## 1. Risk register

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Hallucinated or misread deadline presented as fact | High — user misses a cycle | Medium | Evidence presence check (deterministic) plus human-audited evidence-support metric; explicit deadline model (type, cycle/year, timezone, rolling); unverified fields excluded from checklist; "verify at source" link on every date; dangerous-error metric; CI gate |
| R2 | Wrong eligibility verdict | High | Medium | Deterministic engine; `unclear` when data missing; show reasons + quotes |
| R3 | Pages change after extraction | Medium | High | Store fetch date and content hash; show "last checked"; re-check job; stale banner |
| R4 | Fetching violates site terms of use | Medium (legal, reputation) | Medium | Respect robots.txt, rate limit, identify user agent, cache; no login scraping; allow takedown requests. **robots.txt compliance is necessary but not sufficient**: it does not resolve terms-of-use limits. Review each source family's terms before adding it to the gold set and record the outcome |
| R5 | Free LLM tier limits or model deprecations | Medium | High | Provider-agnostic interface; caching; local fallback |
| R6 | User profile data privacy | Medium | Low-Medium | Minimal profile; no sensitive IDs; store locally or per-account; delete-my-data endpoint; no profile data in logs |
| R7 | Scope creep (essay help, auto-apply) | Medium (never finishes) | High | Non-goals in brief; milestone gates |
| R8 | Gold set labeling bias | Medium | Medium | Frozen snapshots; second-pass labels; held-out split |
| R9 | Prompt injection from scraped pages | Medium | Low-Medium | Treat page text as untrusted data; structured output only; no tool access in extraction step |
| R10 | Over-claiming accuracy in README | Reputation | Medium | Publish exact numbers, dates, set size, and limitations |
| R11 | Publishing stored page snapshots raises copyright / terms-of-use concerns | Medium (legal, takedown) | Medium | Keep full snapshots private by default; publish only labels, short quotes with source URLs, content hashes, and a script that re-fetches snapshots; publish a full snapshot only where the source's terms or license clearly allow it; honor takedown requests promptly |
| R12 | Advisory LLM confidence mistaken for reliability | Medium | Medium | Label it advisory in UI and docs; never use it in eligibility or checklist logic; report its usefulness only as a diagnostic |
| R13 | Eligibility rule interpretation errors (for example GPA scale conversion) | High | Medium | Provenance per rule (ID, version, rationale, source note, tests); every verdict cites the rule version; rules reviewed by you before merge |

## 2. 4D framework mapping for this project

| D | What it means here | Where it shows up |
|---|---|---|
| **Delegation** | Decide what AI coding assistants build vs. what you own: you own architecture decisions, the gold set labels, the eligibility rules, and every merge; AI drafts boilerplate, tests, parsers, and UI scaffolding. | Issue labels `delegate:ai` / `delegate:human`; PR template field "what was AI-generated" |
| **Description** | Write clear specs before prompting: docs, ADRs, issue acceptance criteria, schemas. | These docs; every issue has acceptance criteria and a definition of done |
| **Discernment** | Never trust output unreviewed: measure it. | Gold set, harness, evidence verifier, error-analysis log |
| **Diligence** | Take responsibility for the result: safety, honesty, licensing, privacy. | Risk register, "verify at source" UX, honest README, robots.txt compliance, license |

## 3. Review checklist for every AI-assisted PR

- [ ] Acceptance criteria from the issue are met and tested.
- [ ] I read and understand every changed line.
- [ ] No hard-coded secrets or personal data.
- [ ] Metrics on the eval subset did not regress.
- [ ] Docs/ADR updated if a decision changed.

## 4. Ethics and honesty statements to include in README

- Information may be outdated or wrong; always confirm on the official page.
- Not affiliated with any scholarship provider.
- Takedown/contact path for site owners.
- Fields marked `unverified` are shown for convenience only and are not used for eligibility or checklists.
- Data is fetched in line with each site's robots.txt, but that does not by itself grant permission to reuse content; see the snapshot policy.
