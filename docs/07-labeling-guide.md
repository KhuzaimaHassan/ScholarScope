# 07 — Labeling guide (v0.1, pilot)

**Status:** Draft for owner review. Revise to v0.2 after the three-program pilot.
**Ownership (4D):** Delegation = `human`. You label by hand. AI may draft this guide, the schema, and the validator, but must not pre-fill gold labels: a label an AI wrote is not an independent check on an AI extractor. AI may later help audit evidence support (doc 03, section 4), never replace your labels.

## 1. What a label is

One JSON file per gold slot page: `eval/gold/<program_slug>.json`, validated against `eval/schema/gold-label.schema.json` by `scripts/validate_gold.py`. A label records:

- **what the page states**, as short verbatim quotes with the normalized value;
- **what the page does not state**, because the extractor must abstain there;
- **what the page points elsewhere for**, because the extractor must not invent it.

Labels contain quotes only, never page contents (ADR 007). Snapshots stay in `eval/snapshots/`, which is git-ignored.

Scope of v0.1: English text on public pages and PDFs. Eligibility probe profiles (doc 03, "5 synthetic profiles per programme") belong to M4 and are not part of this pilot.

## 2. Workflow per page

1. Open the slot URL from `docs/06-gold-set-candidates.md`. Note today's date.
2. Save the original: HTML via "Save page as" to `eval/snapshots/<slug>.html`, or the PDF to `eval/snapshots/<slug>.pdf`.
3. Save a plain-text copy as `eval/snapshots/<slug>.txt` (select all and paste for HTML; `pdftotext -layout` for PDF). The validator uses it to confirm every quote really appears on the page.
4. Hash the original. PowerShell prints uppercase, and the schema needs lowercase:
   `(Get-FileHash eval\snapshots\<slug>.html -Algorithm SHA256).Hash.ToLower()`
5. Copy `eval/gold/_example-fictional.json` to `eval/gold/<slug>.json` and edit it. The slug must equal the file name.
6. Start a timer. Label in this order: source, fields, deadlines, conditions. Copy-paste quotes; never retype them.
7. Run `python scripts/validate_gold.py` and fix every error.
8. Write `minutes_spent`, log every judgment call in `docs/labeling-decisions.md` (template in section 8), and commit the label only. `git status` must show nothing under `eval/snapshots/`.

## 3. Fields

| Field | Value shape |
|---|---|
| `program_name` | string, as the page names it |
| `institution` | string, awarding or hosting organisation |
| `degree_levels` | list of `bachelor`, `master`, `phd`, `postdoc`, `other` |
| `funding_coverage` | list of `{item, amount?, amount_max?, currency?, period?, note?}`; `item` is `tuition`, `stipend`, `travel`, `insurance`, `housing`, `visa`, `other`; `period` is `one_time`, `month`, `year`, `programme` |
| `required_documents` | list of strings, one per document, as named on the page |
| `recommenders` | `{count_min?, count_max?, type?}` |
| `application_link` | the page's own application URL |
| `deadlines[]` | `{label, type, cycle_year, date, time, timezone, rolling, status, evidence}`; `type` is `application`, `document`, `recommender`, `scholarship`, `interview`, `other` |
| `conditions[]` | `{kind, value, required, applies_to, evidence}`; `kind` is `min_gpa`, `degree_held`, `nationality_allowed`, `nationality_excluded`, `residency`, `enrollment_status`, `age_min`, `age_max`, `work_experience`, `language`, `field_of_study`, `other` |

Value shapes the validator enforces: `min_gpa` is `{value, scale}`; `language` is `{logic: "any"|"all", options: [{test, min_overall, min_subscore?}]}`.

## 4. Status meanings

| Status | Use when | `value` | `evidence` |
|---|---|---|---|
| `present` | the page states it explicitly | required | at least one quote |
| `absent` | the page does not state it and does not point to where it is | null | none |
| `in_linked_document` | the page says it is in another document or page | null | none; set `linked_url` |
| `ambiguous` | the page states it in conflicting or unclear ways | null | at least one quote; candidates in `notes` |

`deadlines_status` uses the same four values for the whole deadline set. `deadlines` must be empty unless it is `present` (or `ambiguous` with candidate entries).

## 5. Normalization

- **Dates:** ISO `YYYY-MM-DD`. Use a year only if the page states it in the same sentence, table row, or the heading that directly governs it. Never infer a year from today's date.
- **Times:** 24-hour `HH:MM`. If the page gives only "midnight", "end of day" or "close of business", leave `time` null and quote the phrase. Do not interpret it.
- **Time zones:** set only when the page names one, and never from the country. Use `unknown` when a time is given without a zone. Map: JST → `Asia/Tokyo`; "Beijing time" → `Asia/Shanghai`; CET → `UTC+01:00`; CEST → `UTC+02:00`; any other explicit abbreviation → `UTC±hh:mm` if unambiguous, otherwise `unknown` plus a note. `timezone` is null when `time` is null.
- **Money:** record amount, currency and period as stated. Never convert currencies or periods. "Up to" → `amount_max`, with a note.
- **GPA:** `{value, scale}` as stated. Never convert. If the scale is not stated, use kind `other` with the text as stated, plus a note. Do not assume 4.0.
- **Degree levels:** map only explicit words: master, MSc, MA, laurea magistrale → `master`; PhD, doctoral → `phd`. "Graduate" alone is `ambiguous`.
- **Nationality:** keep the page's wording ("developing countries" stays as is). Do not expand to country lists.

## 6. Quote rules

- Verbatim, 400 characters or fewer, copied from the page. The validator normalizes whitespace, smart quotes and dashes only.
- Quote the shortest passage that carries the fact. Use several quotes when a fact is split (for example amount and period in different sentences).
- Repeated text: add `context_before` or `context_after` (80 characters or fewer) so the quote is unique.
- PDFs: quote after text extraction and keep the printed form (including hyphenation). Add `locator` such as `p.3, table 2`. For table rows, quote the row text or the cell that carries the fact.

## 7. Edge cases

1. **Linked information.** Do not follow links. Label `in_linked_document` and set `linked_url`. (Politecnico deadlines live in a linked document.)
2. **"Not required".** An explicit "no GRE needed" is a `present` condition with `required: false`. For recommenders, use `{count_min: 0, count_max: 0}`.
3. **Conflicting statements.** Two different deadlines for the same thing: `ambiguous`, both quotes, value null.
4. **Several cycles on one page.** One deadline entry per cycle, each with its own `cycle_year`. `source.cycle_label` names the page's main cycle.
5. **Closed or stale pages.** Label what the page says and set `source.page_state` (`closed`, `upcoming`, ...). Never update to the current cycle.
6. **Several routes.** For pages with pathways (Type A and Type B, embassy route and university route), put the route in `applies_to` and in the deadline `label`.
7. **Alternatives.** "IELTS 6.5 or TOEFL 90" is one `language` condition with `logic: "any"`. Other "or" text stays one condition with the value as stated.
8. **Same fact, several places.** Label it once; add the extra quotes as further evidence.
9. **Marketing and incidental text.** Ignore testimonials, news and general promotion. Label only what states a requirement, amount, date or process.
10. **Overview and listing pages.** Pages that describe several schemes (Politecnico overview, Study in Italy calls, DAAD overview) are not in the pilot. After the pilot, decide whether they need a different label shape.
11. **Bilingual pages.** Label and quote only the English text.
12. **No application link.** If the page says "apply online" but gives no link target, `application_link` is `absent`.

If a case is not covered, choose the more conservative status (`ambiguous` over `present`, `absent` over a guess), then log the decision.

## 8. Pilot protocol

Pick pages that cover the layouts the extractor will meet. These come from the notes in `docs/06`; confirm by reading each page first.

| Order | Slot | Why it is in the pilot |
|---|---|---|
| 1 | Netherlands 3, Radboud Scholarship Programme | Clean static HTML with eligibility, GPA, deadline, references and funding. The easy baseline. |
| 2 | Japan 3, Honjo 2027 guidelines (PDF, 5 pages) | PDF text and tables; conditions on level, nationality, age, language; "graduate" wording to settle. |
| 3 | Netherlands 4, University of Twente NL Scholarship | Finder-style HTML layout; replaces the excluded Politecnico overview redirect. |

This pilot covers a finder-style layout but does **not** cover the stale-cycle or linked-document case. Both remain untested until a replacement for Italy 1 is found. On 2026-10-18 the Italy 1 URL redirected to the slot 2 overview. The only same-host merit-based link found there was a PDF call covering several scholarship categories, not one scholarship, so it was not selected.

Preparation limitation (2026-10-18): the Twente fetch returned HTML successfully, but the current cleaner produced an empty `.txt` copy. That copy is not usable for quote validation yet; no alternate extraction or labels were supplied. The committed pilot JSON files are explicitly marked mechanical skeletons, not completed hand-written labels; their `absent` statuses and labeler date/time entries are placeholders only.

Protocol:

1. Label the three in order. Record `minutes_spent` for each, including snapshot and hashing.
2. Log each judgment call in `docs/labeling-decisions.md`:
   `| date | slot | situation | decision | rule it should become |`
3. After at least three days, relabel the Radboud page blind (without opening the first label), then compare field by field: status and value. Report the agreement and the disagreements. There is no pass/fail target for the pilot. Every disagreement is a guide fix.
4. Update this guide to v0.2 from the decision log, and update the time estimate in `docs/06` from the measured minutes.
5. Then label the remaining shortlist pages (17 slots). Shortlist families come first, as in doc 03.

Pilot done when: three labels pass the validator, times are recorded, the decision log has entries, and the guide is revised.

## 9. Repo wiring (one-time)

- Add `eval/snapshots/` to `.gitignore` (Ruff already excludes it).
- CI installs only Ruff, pytest and mypy. Add `jsonschema` to the CI install line so `tests/test_validate_gold.py` runs, and document `pip install jsonschema` for local use.
- Labels are committed one PR per batch; the PR template's AI-assistance section should say the labels were hand-written.
