# Private snapshots and public drift metadata

ADR 007 applies: **snapshots and page contents must never be committed**.
`eval/snapshots/` is git-ignored. Check `git status` and
`git ls-files eval/snapshots` before committing; the latter must print nothing.
The public `eval/manifest.json` starts empty in this PR: no real-site data was
fetched or added. The owner populates it after labeling.

## Storage and API

`snapshot_page(fetch_result, slug, *, snapshots_dir=eval/snapshots)` requires a
successful HTML/PDF FetchResult. It writes original bytes to `<slug>.html|pdf`
and the cleaner/extractor text to `<slug>.txt`, UTF-8 with unchanged line breaks.
Each file is atomically replaced, but the pair is not a transactional bundle.
The function returns a metadata-only, frozen Pydantic SnapshotRecord. It does
not fetch URLs, read labels, or write into the repository's `eval/gold/`.
Invalid slugs, MIME types, timestamps and hash mismatches are rejected before
slug files are written. `retrieved_on` is the fetch timestamp's UTC date.

Public fields: slug, original/final URL, retrieved_on, format, **bytes (a count,
not raw bytes)**, lowercase raw `content_sha256`, `cleaned_text_sha256`,
text_chars, cleaner_version or pdf_extractor_version (the other is null),
segmenter_version, passage_count and extraction_status. No title, text, snippet,
DOM, PDF, label values or raw content can be serialized into an entry.
The manifest is keyed by slug; each key must equal its entry's slug. It is built
from label program_slug/source.url plus successful snapshot records, not claims.
Its schema is `eval/schema/snapshot-manifest.schema.json`.

The cleaned hash is SHA-256 of UTF-8 `" ".join(cleaned_text.split())`: whitespace
only, not NFKC, case folding, verifier formatting normalization or rewriting.
text_chars counts the original cleaner/extractor text, not the collapsed hash
input. An unsupported/invalid PDF keeps private bytes and empty text, zero
passages, and an explicit extraction_status; it is **not** usable text. An empty
cleaned hash does not establish content equivalence for unreadable PDFs.

`CLEANER_VERSION="1"`, `PDF_EXTRACTOR_VERSION="1"` and existing
`SEGMENTER_VERSION="1"` identify behavior. **Any behavior change must bump its
version.** The constants added here do not change extraction behavior.

## Drift classes and precedence

1. Raw hashes equal: `unchanged`, even if tool versions differ. This describes
   raw bytes, not a guarantee that different tools would yield identical text.
2. Raw differs and cleaner/PDF-extractor or segmenter versions differ:
   `tool_version_changed`. Do not compare cleaned hashes across tool versions.
3. Raw differs, versions equal, cleaned hashes equal: `benign_raw_change`, such
   as a rotating nonce attribute. This is a text-level diagnostic, not proof
   that layout, hidden content or scholarship semantics stayed the same.
4. Otherwise: `content_changed`. Inspect privately; never silently revise labels.

## Re-fetch command

```sh
python scripts/refetch_snapshots.py
python scripts/refetch_snapshots.py --update-manifest
python scripts/refetch_snapshots.py --snapshots-dir eval/snapshots/review-run
```

The script reads real `eval/gold/*.json` files, **including skeletons**, without
validating or modifying label claims. Underscore examples such as
`_example-fictional.json` are skipped, matching the label validator convention.
It uses Fetcher sequentially with its robots/redirect policy, identifying user
agent, size cap, timeouts and per-host pacing. No logins, workarounds, mirrors,
Playwright or LLM calls. A fresh process refetches; Fetcher's cache is per instance.

By default originals/text copies go to **eval/snapshots/refetched/**, and Fetcher's
hash-addressed copies to its `fetched/` child. This deliberately preserves the
hand-labeling originals at eval/snapshots/<slug>.* (doc 07). Do not point
--snapshots-dir at those frozen originals: explicit output replaces slug files.
Choose a fresh private directory to keep several review runs. Output under a
gold-label directory is rejected. `--gold-dir` and `--manifest` support isolated
local/test runs; use them deliberately, never put content in the public manifest.

The printed table shows slug, fetch status, drift class and old/new raw/cleaned
hash prefixes (12 characters). `new` means no baseline entry exists. Failures
(blocked/not_found/network_error) are reported per slug and preserve old entries;
other sources continue. Drift and those fetch failures exit **0**. Script errors
(bad metadata/JSON, unsupported MIME, file errors, invalid options) exit **1**.
Non-ok PDF extraction is printed explicitly, not passed off as meaningful text.

Without --update-manifest, the baseline file is untouched (private files are
still written). With it, successful entries update the metadata baseline, failed
entries remain, and a script error prevents writing the manifest. Review drift
before accepting a new baseline. Labels' recorded source hashes are never
updated automatically, and no match with those frozen hashes is implied.

No live re-fetch was run for this task. Tests use only a localhost fake server,
synthetic HTML, generated PDFs and temporary directories. Docs 05 and 07 are
unchanged: their frozen, private hand-labeling workflow remains valid.
