# 22 — Static evidence report

`scholarscope.report.render_report(result, *, now, reference_tz=UTC,
source_url_is_user_supplied=...)` returns a complete, standalone HTML document.
It is a local view of a pipeline result, not a server, an editor, a profile
eligibility assessment or an extraction-quality measurement. Quote presence
does not establish that the quote supports a value. No new eligibility rules,
matching rules or checklist policy are introduced.

## Local use

```sh
python scripts/render_report.py --slug fictional-award --source-url https://example.invalid/award
```

The script reads exactly one local `<slug>.html` or `<slug>.pdf` from
`eval/snapshots/` (override with `--snapshots-dir`). It never fetches a page. The
default output is `eval/reports/<slug>-report.html`, which is gitignored.
Configuration comes from the process environment; `.env` is not loaded
automatically. Cache mode is forced to `read_only`, even if the environment
requests writes or disables caching. A cache miss becomes a failed group in the
report, with no provider call. The file is still written when all groups fail;
the command exits with status 1 for an unsuccessful pipeline result.

`--live` explicitly uses `LLMConfig.from_env()` without the cache-only override
and can send snapshot passages to the configured provider. It is not required
to view an existing cached result. Tests use scripted FakeClient responses or
cache misses, with network access blocked; they do not make real model calls.

`--source-url` must be HTTP(S), without credentials, whitespace or control
characters. It supplies source metadata and the cleaner's relative-link base
for a local file, under the [pipeline base rule](16-extractor.md). It does not
establish verified retrieval provenance. The header labels its timestamp
**local read date**. The only external hyperlink is this explicitly supplied
source URL. Application links, linked-document URLs and any URLs in extracted
content remain plain text. Evidence links are local passage anchors.

`--out` permits an HTML path under `eval/reports/` or, when explicitly supplied,
`docs/examples/`. Other destinations, including `eval/gold/`,
`eval/snapshots/` and other documentation directories, are refused before a
client is constructed. Paths are resolved before checking, including traversal
and symlinks; redirecting an approved directory outside its allowed root is
also refused.

## What it shows

- Program/source metadata, processing and prompt versions, per-group statuses,
  failed groups, failure **categories only**, rejected group/index/reason, and
  input-truncation counters. Provider messages, raw responses, raw rejected
  items and free-form pipeline errors are never included, even when the result
  contains them in memory. This preserves ADR 020's persistence boundary.
- Fields with separate content-status and verification badges; failed groups
  read **NOT EXTRACTED (group failed)** rather than implying successful absence.
  Unverified claims remain visible and excluded from checklist logic.
- Deadlines with date, time, timezone, type, comparison/resolution and checklist
  warnings; conditions with kind, value, required flag and evidence.
- The unchanged `build_checklist(record, now, reference_tz=...)` output: due
  dates, warnings, policy ID/version and evidence. Unverified or ambiguous
  claims request a check of the official page. Profile eligibility is absent.
- Cleaned source passages with local evidence links and highlights from the
  verifier's original half-open offsets. A quote spanning adjacent passages
  highlights each overlap. Synthetic link-target spans are labelled **link
  target added by the cleaner**; injection findings are labelled **flagged as
  suspicious (advisory)**. Neither label is an additional verification verdict.

`PipelineResult.document` exposes the already-created immutable segmented
document for this view, including empty-text results when segmentation ran. It
defaults to `None` for callers constructing results without source passages.
The report does not re-clean or re-match text. Its caller supplies an aware
`now`; that same instant is used for the checklist and generated timestamp.

## Safety and display limits

All dynamic strings are HTML-escaped. There are no scripts, event handlers,
forms, images, iframes, external fonts or other remote resources. One static
style block is allowed by the exact CSP `default-src 'none'; style-src
'unsafe-inline'`. Only validated, explicitly supplied source hyperlinks have
external `href` attributes, with `rel="noopener noreferrer nofollow"`; other
links use generated local anchors. No data supplies CSS or element attributes.

Each displayed value, quote, note, version entry or passage is limited to
**2,000 original characters**, followed by a visible **… truncated** label.
Unicode format controls (including direction overrides) are displayed as
`[U+XXXX]` markers. Highlight intervals are calculated on the original text
before clipping, escaping or displaying these controls, so original offsets
remain authoritative. Text beyond the display limit is not shown, including
highlights there. The report is a readable view, not a lossless record export.

Reports contain source text and extracted claims and should remain private for
real snapshots. The output is inert, not anonymized. No accuracy, precision,
recall or model-confidence indicators are produced. The footer reminds readers
to confirm on the official page; offline tests validate software contracts,
not real-model compliance or semantic support.

## Reproduce the synthetic example

[Example report](examples/sample-report.html) is **SYNTHETIC**, with a prominent
banner: fictional source text and scripted extraction, not a real model run.
Regenerate from the repository root without a key or network:

```sh
python scripts/render_report.py --synthetic-sample --out docs/examples/sample-report.html
```

`tests/report_fixtures.py` builds Example Excellence Scholarship with FakeClient,
fixed IDs and a fixed timestamp. The flag cannot be combined with live/source
inputs. A test compares the committed file with the generator byte-for-byte.
The example demonstrates presentation only and makes no quality claim.
