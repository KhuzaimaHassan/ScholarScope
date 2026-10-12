# 01 — Product Brief

**Name:** ScholarScope (final) · **License:** MIT
**Status:** Draft v0.2 — reviewed and approved with edits; docs-first, no code yet

## 1. Problem

Applicants to fully funded scholarships and graduate programs must collect requirements from scattered, inconsistent web pages: deadlines, eligibility rules, funding terms, required documents, language-test thresholds, recommender rules. They end up with spreadsheets of facts they cannot fully trust. A missed condition or a wrong deadline costs an entire application cycle.

## 2. Solution (one sentence)

Paste a scholarship or program URL; ScholarScope extracts the requirements into a structured record where **every field links to the exact source passage**, checks them against your profile, and produces a dated checklist — marking anything it cannot verify as **"unverified — check official page"** instead of guessing.

## 3. Target users (personas)

| Persona | Need | Success looks like |
|---|---|---|
| **Applicant (primary)** — final-year undergrad / recent grad applying to 5–20 funded programs | Know fast: am I eligible, what is missing, when is it due | Trusts the output enough to plan from it, and verifies in one click |
| **Contributor (secondary)** — developer adding support for a new university/site | Clear plugin interface and a test set | Adds a new site parser in under a day |
| **Reviewer (tertiary)** — recruiter / engineer testing the demo | Try a link, see a result, check it against the source | Understands the value in under 60 seconds |

## 4. Core user flow

1. User creates a lightweight profile (degree, field, GPA, nationality, language scores, documents they already have).
2. User pastes one or more program/scholarship URLs.
3. System fetches, cleans, and extracts a **Requirement Record** with evidence for every field.
4. System runs deterministic eligibility checks against the profile → `eligible / not eligible / unclear`, each with the reason and the source quote.
5. System generates a checklist with dates (deadline minus buffers) and missing documents.
6. User can open any claim and jump to its source passage.

## 5. Scope

### In scope (v1)
- Public web pages and public PDFs for funded programs.
- Extraction fields: program name, institution, country, degree level, funding coverage, deadline(s), eligibility conditions (min GPA, degree, nationality, age, work experience), required documents, language-test requirements, recommender requirements, application link.
- Evidence-linked extraction with automatic evidence verification. Fields that fail verification are **retained but marked `unverified` and excluded from eligibility and checklist logic**.
- Explicit deadline modeling: deadline type (application, document, recommender, scholarship, interview), cycle/year, timezone, rolling status, and multiple deadlines per program.
- LLM confidence scores are **advisory only** (display and triage); they never influence eligibility verdicts.
- Deterministic eligibility engine and checklist generator.
- Web UI + REST API + CLI-free demo path (paste URL, see result).
- A public, hand-labeled evaluation set and published accuracy numbers.
- Contributor plugin interface for site-specific parsers.

### Out of scope (non-goals)
- Auto-submitting applications or logging in to application portals.
- Writing SOPs/essays (a different problem; keep this tool about facts).
- Scraping behind logins or ignoring robots.txt / site terms.
- Guaranteeing correctness: the product's promise is *traceable* facts, not *infallible* facts.
- Mobile app.

## 6. Success criteria

| Area | Target (initial proposal — revise after M3 baseline) |
|---|---|
| Deadline extraction exact-match | ≥ 90% on gold set |
| Evidence presence (quote exists in the cited passage) | 100% of fields shown as `verified` (deterministic invariant; failures become `unverified`) |
| Evidence support (quote actually supports the extracted value) | Human-audited sample; target ≥ 95% on 50 sampled fields |
| Eligibility verdict agreement with hand labels | ≥ 85%, with "unclear" preferred over a wrong verdict |
| Time from URL to result | < 30 s median |
| Hosting cost | $0–5/month on free tiers |
| Demo | Public hosted demo + README GIF + 20 pre-loaded example programs |

## 7. Portfolio / open-source / product angle

- **Resume story:** built to solve my own application problem; accuracy measured on a public benchmark.
- **Open source:** MIT-licensed core (Apache-2.0 can be reconsidered later if patent protection matters); good-first-issues = "add parser for site X", "add gold-set entries".
- **Product option (later, not v1):** hosted tier with deadline reminders and saved programs. Decision deferred until real usage exists.

## 8. Branding decision

Lives on the personal GitHub (KhuzaimaHassan), separate from any anonymous product brand.

## 9. Decisions and open questions

**Decided**
- Name: ScholarScope. License: MIT.
- Gold set: **nine program families, four programs each (36 programs)**, growing to 60+. Original five: Germany (DAAD-type), UK (Chevening-type), US (Fulbright-type), South Korea (GKS-type), China (CSC-type, Type A and B). Added to match the real application shortlist: Erasmus Mundus (joint masters), Netherlands (university scholarships), Japan (MEXT plus private foundations), Italy (Politecnico di Milano plus other Italian scholarships). No family is dropped; the well-known ones also make the public demo easy to test. Each family mixes HTML, PDF, JS-heavy, and multi-page sources.

**Open**
- Data freshness: re-check pages weekly? (Decide at M5.)
- Domain name (register in M0).
- Snapshot policy: which stored page snapshots may be published in the repo versus kept private (see `04-risks-and-diligence.md`, R4 and R11). `robots.txt` compliance alone does not settle terms-of-use or copyright questions.
