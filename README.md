# ScholarScope

ScholarScope is an evidence-first tool for researching fully funded scholarships and graduate programs.

## Problem

Applicants must collect deadlines, eligibility rules, funding terms, required documents, language-test thresholds, and recommender requirements from scattered web pages and PDFs. A missed condition or incorrect deadline can cost an entire application cycle.

ScholarScope is designed to turn an official program URL into a traceable requirement record: every displayed claim should link to its source passage, uncertain claims should be marked `unverified`, and eligibility verdicts should be computed by deterministic code rather than by an LLM.

## Project status

The Python pipeline and planning components below exist and have synthetic unit tests. The web product and eligibility rule engine are still planned. "Built and unit-tested" describes software contracts, not measured scholarship extraction quality.

No accuracy numbers are published yet. The 36-program gold set is being hand-labeled; results will be added with date and versions once a baseline exists.

| Stage | What exists / contract | Status |
|---|---|---|
| HTTP fetcher | [fetcher.py](scholarscope/fetcher.py): robots checks, host-restricted redirects, private snapshots; [snapshot contract](docs/14-snapshots.md) | built and unit-tested |
| HTML cleaner with link targets | [cleaner.py](scholarscope/cleaner.py): text, node offsets and synthetic anchor-target spans; [doc 08](docs/08-html-cleaner.md) | built and unit-tested |
| PDF text | [pdf_text.py](scholarscope/pdf_text.py): page text, offsets and unsupported statuses; [doc 09](docs/09-pdf-extraction.md) | built and unit-tested |
| Segmenter | [segmenter.py](scholarscope/segmenter.py): deterministic passage IDs and source references; [doc 12](docs/12-segmenter.md) | built and unit-tested |
| Snapshot store | [snapshots.py](scholarscope/snapshots.py): raw/cleaned hashes, private files and version-aware drift; [doc 14](docs/14-snapshots.md) | built and unit-tested |
| Playwright fallback | [renderer.py](scholarscope/renderer.py) and [prepare_page](scholarscope/pipeline.py): only suspiciously-empty HTTP HTML; [doc 19](docs/19-rendering-fallback.md) | optional, advisory CI |
| Requirement Record | [schema.py](scholarscope/schema.py): typed claims, evidence and separate verification; [doc 10](docs/10-requirement-record.md) | built and unit-tested |
| LLM interface: Gemini, Groq, Ollama | [llm/](scholarscope/llm): plain-httpx adapters, validation, retries, cache and FakeClient; [doc 15](docs/15-llm-interface.md) | built and unit-tested |
| Field-group extractor | [extraction/](scholarscope/extraction) and [pipeline.py](scholarscope/pipeline.py): group prompts, local validation and mandatory verification; [doc 16](docs/16-extractor.md) | built and unit-tested |
| Injection defenses | [request fencing](scholarscope/llm/base.py), [URL guard](scholarscope/extraction/guards.py) and [advisory scan](scholarscope/extraction/injection_scan.py); [doc 17](docs/17-threat-model-injection.md) | built and unit-tested |
| Evidence verifier | [verifier.py](scholarscope/verifier.py): formatting-tolerant quote presence, original offsets; [doc 13](docs/13-verifier.md) | built and unit-tested |
| Deadline model | [schema.py](scholarscope/schema.py) and [deadlines.py](scholarscope/deadlines.py): explicit date/zone resolution and conservative comparison; [doc 11](docs/11-deadlines.md) | built and unit-tested |
| Evaluation harness | [eval/](scholarscope/eval) and [run_eval.py](scripts/run_eval.py): failure-aware metrics, provenance and human audit export; [doc 18](docs/18-evaluation-harness.md) | built and unit-tested |
| Profile schema | [profile.py](scholarscope/profile.py): private typed inputs and exact-scale GPA lookup, no conversion; [doc 20](docs/20-profile.md) | built and unit-tested |
| Checklist generator | [checklist.py](scholarscope/checklist.py): verified-only dates, explicit buffer policy and timezone warnings; [doc 21](docs/21-checklist.md) | built and unit-tested |
| Static evidence report | [report.py](scholarscope/report.py): inert local HTML, source highlights and checklist; [doc 22](docs/22-evidence-report.md) | built and unit-tested |
| Eligibility rule engine | Design only: [architecture](docs/02-architecture.md), [ADR 004](docs/adr/004-deterministic-eligibility-engine.md) | not started |
| Missing-document detector | Planned in [M4](docs/05-milestones-and-issues.md); checklist preparation items do not compare profile holdings | not started |
| API | Planned in [M5](docs/05-milestones-and-issues.md) | not started |
| Database | Planned in [M5](docs/05-milestones-and-issues.md) | not started |
| Web UI | Planned in [M5](docs/05-milestones-and-issues.md) | not started |
| Deployment | Planned in [M6](docs/05-milestones-and-issues.md); no hosted product is supplied | not started |

## How it works

**SYNTHETIC Example report:** [fictional, scripted HTML sample](docs/examples/sample-report.html), not a real model run. [Generate a local report](docs/22-evidence-report.md) from cached extraction without provider calls.

```text
Official URL -> Fetcher -> HTML cleaner / PDF text -> Segmenter
             -> Field-group extractor -> Evidence verifier -> Requirement Record
                                                           -> Checklist generator
                                                           -> Eligibility engine (planned)
                                                              -> Profile-aware checklist (planned)
```

This follows the [architecture](docs/02-architecture.md); the current checklist can plan directly from verified records, while eligibility/profile integration remains future work.

- **Evidence or abstain:** only the deterministic verifier establishes quote presence. Presence does not prove that a quote supports the value. [ADR 003](docs/adr/003-evidence-verification-is-code.md), [matching rules](docs/adr/012-verifier-matching-rules.md).
- **LLMs extract, code decides:** extraction produces typed claims; deadline/checklist logic is deterministic. The planned eligibility engine follows the same boundary. [ADR 004](docs/adr/004-deterministic-eligibility-engine.md).
- **Unverified is excluded from logic:** failed claims retain their values and quotes, but cannot supply dates or eligibility inputs. Unchecked claims are also unusable. [ADR 008](docs/adr/008-unverified-fields-retained-but-excluded.md), [two-axis model](docs/adr/010-two-axis-field-status.md).

## Quickstart

Use Python **3.11 or newer**, Git and an isolated Python environment. From a fresh clone:

```sh
git clone https://github.com/KhuzaimaHassan/ScholarScope.git
cd ScholarScope
python -m venv ../scholarscope-venv
```

Activate with `source ../scholarscope-venv/bin/activate` on POSIX shells, or `..\scholarscope-venv\Scripts\Activate.ps1` in PowerShell. The environment is outside the checkout. Install the actual `test` extra and the quality tools:

```sh
python -m pip install -e ".[test]" ruff mypy
ruff check .
mypy .
pytest -q
```

No real keys are needed for tests. They use fictional inputs, FakeClient/mock transports and local HTTP servers. Optional browser tests skip with a reason when Playwright or Chromium is absent. [CI](.github/workflows/ci.yml) runs the quality checks and a separate advisory browser job.

To include the optional local browser tests:

```sh
python -m pip install -e ".[render,test]"
python -m playwright install chromium
pytest -q -m browser tests/test_renderer.py -rs
```

Rendering is a restricted fallback, not an override: only the cleaner's `suspiciously_empty` heuristic triggers it through `prepare_page`. It respects robots, restricts hosts and stops at detected bot walls; see [doc 19](docs/19-rendering-fallback.md).

### Manual extraction from a local snapshot

`eval/snapshots/` is private and gitignored; private page files are not included in a fresh clone. You must obtain snapshots yourself using robots-respecting fetching and the applicable [source terms](docs/source-terms.md). Do not bypass a block or commit page contents. Keep exactly one `eval/snapshots/my-local-page.html` **or** `my-local-page.pdf` for the example below; replace the slug with your own.

If `.env` does not already exist, copy the template (`cp .env.example .env` on POSIX, `Copy-Item .env.example .env` in PowerShell). Edit **only your local `.env`**: choose Gemini/Groq and a compatible `LLM_MODEL`, and fill the corresponding key there. Ollama uses a separately running local server/model instead of a cloud key. The template defaults to `fake`, which is for synthetic behavior, not a real extraction demonstration. Never commit `.env` or print its contents.

The application reads process environment variables; it **does not auto-load `.env`**. For the template's simple, unquoted `KEY=value` entries, load your own trusted file in one of these ways:

POSIX shell:

```sh
set -a
. ./.env
set +a
```

PowerShell (only the supported names are loaded; values are not printed):

```powershell
Get-Content -LiteralPath .env | ForEach-Object {
    if ($_ -match '^(LLM_PROVIDER|LLM_MODEL|GEMINI_API_KEY|GROQ_API_KEY|OLLAMA_BASE_URL|LLM_TIMEOUT_SECONDS|LLM_CACHE_MODE)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
```

Then run manually from the repo root:

```sh
python scripts/extract_snapshot.py --slug my-local-page --snapshots-dir eval/snapshots
```

This reads the local file and may send its passages to the configured LLM; it does not fetch the source page or write labels/snapshots. It prints the record plus verification/failure diagnostics. Read `failed_groups` and `rejected_items`: extraction-failure placeholders do not mean the page states nothing. A `read_only` cache avoids provider calls, but cache misses cannot produce an extraction.

Add `--source-url https://example.invalid/award` to supply the original HTTP(S) URL as source metadata and the base for relative links; output marks it as user-supplied, not verified retrieval provenance. Without it the source remains a local file URI. The date remains the local read date. Rejections show group/index/reason; `--show-rejected` opts into private raw items. Failure diagnostics include guarded provider messages for console use only: do not redirect or save this output to reports/logs. Private caches and raw extraction output may contain page text; see [doc 16](docs/16-extractor.md).

## Roadmap

| Milestone | Current state |
|---|---|
| M0 — Foundations and docs | Built: docs, ADRs, templates and CI. The separate [domain task](https://github.com/KhuzaimaHassan/ScholarScope/issues/6) remains open. |
| M1 — Fetch, clean, segment | Built and unit-tested, including private snapshot tooling and optional rendering. |
| M2 — Evidence-linked extraction | Built and unit-tested; real-world accuracy and model compliance are not established. |
| M3 — Gold set and evaluation | Harness built; hand labels, baseline results, support audit and evaluation CI gate pending. |
| M4 — Eligibility and checklist | Partly built: profile schema and checklist exist; rules, verdicts and missing-document detection remain. |
| M5 — API and UI | Not started. |
| M6 — Deploy and polish | Not started: deployment/demo work remains; this README is preparation only. |
| M7 — Open-source readiness | Not started for plugin/release work; [contribution guidance](CONTRIBUTING.md) and existing templates are preparation, not completion of the milestone. |

See the [issue plan](docs/05-milestones-and-issues.md) for planned scope. Some early architecture/plan wording describes future behavior; the status table above distinguishes implemented modules from plans.

## Documentation

- [01 — Product brief](docs/01-product-brief.md): problem, scope and intended product.
- [02 — Architecture](docs/02-architecture.md): components and planned integration.
- [03 — Evaluation plan](docs/03-evaluation-plan.md): label design and intended measurements.
- [04 — Risks and diligence](docs/04-risks-and-diligence.md): privacy, source rights and review responsibilities.
- [05 — Milestones and issues](docs/05-milestones-and-issues.md): planned phases and acceptance criteria.
- [06 — Gold-set candidates](docs/06-gold-set-candidates.md): source slots and owner decisions.
- [07 — Labeling guide](docs/07-labeling-guide.md): maintainer hand-labeling rules and pilot.
- [08 — HTML cleaner](docs/08-html-cleaner.md): text, link targets and source maps.
- [09 — PDF extraction](docs/09-pdf-extraction.md): page locators and unsupported inputs.
- [10 — Requirement Record](docs/10-requirement-record.md): field shapes, content status and verification.
- [11 — Deadlines](docs/11-deadlines.md): resolution and conservative global comparison window.
- [12 — Segmenter](docs/12-segmenter.md): passage boundaries, IDs and offsets.
- [13 — Verifier](docs/13-verifier.md): quote-presence outcomes and normalization limits.
- [14 — Snapshots](docs/14-snapshots.md): private bytes, public metadata and tool-version drift.
- [15 — LLM interface](docs/15-llm-interface.md): providers, config, validation, retries and caching.
- [16 — Extractor](docs/16-extractor.md): field groups, local execution and failure handling.
- [17 — Injection threat model](docs/17-threat-model-injection.md): trust boundaries and residual risks.
- [18 — Evaluation harness](docs/18-evaluation-harness.md): metrics, exclusions and private human-audit export.
- [19 — Rendering fallback](docs/19-rendering-fallback.md): optional browser policy and advisory tests.
- [20 — Profile](docs/20-profile.md): private inputs and no GPA conversion.
- [21 — Checklist](docs/21-checklist.md): buffer policy and cross-calendar safety.
- [Source terms](docs/source-terms.md): per-source robots/legal review and contact routes.
- [Contributing](CONTRIBUTING.md): development, PR and data-integrity rules.

The [ADR index](docs/adr/README.md) includes the foundation decisions and these later contracts:

- [010 — Two-axis field status](docs/adr/010-two-axis-field-status.md): distinguish content claims from verification.
- [011 — Passage IDs](docs/adr/011-passage-ids-and-segmentation.md): deterministic segmentation and source references.
- [012 — Verifier matching](docs/adr/012-verifier-matching-rules.md): formatting tolerance without character-edit matching.
- [013 — Field-group extraction](docs/adr/013-field-group-extraction-and-wire-schemas.md): small provider wire schemas, local validation.
- [014 — Injection defenses](docs/adr/014-prompt-injection-defenses.md): fencing, URL provenance and advisory findings.
- [015 — Link targets](docs/adr/015-link-targets-in-cleaned-text.md): synthetic anchor provenance and cleaner-version changes.
- [016 — Evaluation failures](docs/adr/016-evaluation-harness-failure-semantics.md): exclusions and honest scoring denominators.
- [017 — Rendering](docs/adr/017-rendering-fallback.md): restricted fallback and reproducible render metadata.
- [018 — Profiles](docs/adr/018-profile-schema-and-no-gpa-conversion.md): private inputs and exact-scale GPA comparison.
- [019 — Checklist buffers](docs/adr/019-checklist-buffers-and-unknown-timezones.md): no unknown-zone buffers and safe calendar exceptions.

## Important limitations

ScholarScope is not affiliated with any scholarship provider. Information can become outdated or be wrong; applicants must confirm requirements and deadlines on the official source before applying.

- `verified` proves quote presence only. A present quote can be misread or contain false information; support and source authority require separate review.
- Unverified/unchecked claims cannot drive checklist dates or the planned eligibility engine. LLM confidence is advisory, never a logic gate. Failed extraction must not be read as genuine absence.
- Injection defenses are tested software boundaries, not proof of real-model compliance. The advisory scan is bypassable; tiny/zero-size and stylesheet-hidden text can survive static cleaning.
- Scanned/low-text and password-required PDFs are unsupported; no OCR is included. Rendering can miss pages outside its thin-text heuristic and never authorizes bypassing a source restriction.
- Unknown source zones receive no date buffers; uncertain global windows and cross-calendar cases may require an undated official-page check. Profile comparison helpers do not convert GPA scales.
- Private snapshots, caches, profiles and audit context must not be committed. Robots permission is not permission to republish a page; follow [ADR 007](docs/adr/007-public-gold-set-private-snapshots.md) and the [source terms](docs/source-terms.md).

Site owners can request removal through the [issue tracker](https://github.com/KhuzaimaHassan/ScholarScope/issues) using the [contribution guide's takedown route](CONTRIBUTING.md#site-owner-takedown-requests). Do not attach private or sensitive material publicly.

## License

ScholarScope is released under the [MIT License](LICENSE).
