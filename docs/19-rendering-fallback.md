# Optional JavaScript rendering fallback

[ADR 006](adr/006-playwright-fallback-only.md) and [ADR 017](adr/017-rendering-fallback.md)
apply. Fetcher.fetch remains plain HTTP. The explicit network-capable
`pipeline.prepare_page(fetch_result, *, allow_hosts=(), ...)` checks successful
HTTP HTML with the existing cleaner. **The only trigger is suspiciously_empty**:
input >5,000 bytes AND cleaned text <200 characters. There is no force-render
parameter or CLI flag. Small JS shells, pages with large navigation but little
content, and other pages outside this heuristic can escape it. Any future ADR
amendment to broaden the trigger needs evidence from real pages; no such evidence
or live evaluation was collected here. PDFs/non-HTML, failed fetches, local files
and already-rendered results never trigger browser work.

## Installation and use

```sh
python -m pip install '.[render]'
playwright install chromium
```

Playwright is an optional render extra only; core imports/HTTP/PDF processing
work without it. A robots-permitted attempt without Playwright or Chromium
returns unavailable with a clear installation message. No automatic downloads.
Fetcher and the ordinary local run_pipeline do not import a browser backend.

Call prepare_page before run_pipeline and check PreparedPage.status. On ok,
pass PreparedPage.fetch_result to run_pipeline or snapshot_page. A render failure
must not silently fall back to thin HTTP bytes. No inference occurs in the
preparation helper; run_pipeline itself remains local and network-free except
for its explicitly supplied LLM client. Frozen local rendered HTML works with
scripts/extract_snapshot.py through the same cleaner/pipeline, with no rendering
flag and no browser launch.

```sh
python scripts/refetch_snapshots.py --snapshots-dir /private/review-run
python scripts/refetch_snapshots.py --snapshots-dir /private/review-run --allow-host assets.example.invalid
```

The hostname is fictional. The repeatable --allow-host option explicitly permits
exact subresource hostnames, never wildcard/URL/port entries. Allow-list entries
are lowercased, deduplicated and sorted; never inferred/defaulted from a page.
The option applies to sources in that invocation, so use a deliberately selected
gold-dir/run for each source policy. A hostname rule covers its ports, just like
the fetcher's hostname redirect comparison; ports are not separate hostnames.
All snapshot output remains private. No live refetch/extraction was run here.

## Network and browser boundaries

render(url, *, timeout=20, settle_ms=1500, max_bytes=15000000,
user_agent=USER_AGENT, allow_hosts=()) returns a frozen RenderResult containing
status, last attempted/final URL, private UTF-8 DOM bytes on success, Playwright
and browser versions, aborted-request count, blocked_hosts, effective allow_hosts,
elapsed seconds and a sanitized error/reason. No page content/errors/headers are
logged. blocked_hosts contains only other-host names, deduplicated, sorted and
capped at the first 20 names; no paths/query strings. The count includes policy
aborts and controlled navigation aborts used to follow checked redirects.

- Before browser launch, use Fetcher's robots cache, status classification and
  path decision via its cancellable asynchronous I/O bridge, with the same
  identifying user agent. 404/410 allow; 401/403 block; redirects in robots are
  not followed; other HTTP/network errors fail without a browser. Recheck each
  allowed HTTP(S) resource/hop, serialize checks, honor per-host pacing and
  explicit robots crawl-delay. A robots error is never permission to render.
- Only the page's exact hostname and explicitly allowed subresource hosts are
  eligible. Images/media/fonts are always aborted. Service workers are disabled;
  WebSockets are closed without connecting. Downloads are disabled. A render
  that stays thin because hosts were blocked is visible via blocked_hosts and
  refetch diagnostics; there is no silent escalation of allowed hosts.
- Every main-document hostname change is render_error with exactly
  redirect_host_change, **including an allow-listed host**. The fetcher's same
  five-hop limit applies, also counting script/meta navigations; loops stop.
  Redirect responses are inspected with redirects disabled before requesting a
  target, so the target cannot bypass robots/host checks. Subresource redirects
  also obey the exact-host rule and hop limit. Their response bytes are fulfilled
  at the original resource request; redirect-dependent module/CSS base semantics
  can differ from unrestricted browsing. This restricted renderer is not a full
  browser-fidelity guarantee.
- Load, then wait a fixed settle_ms, then page.content(); no clicks, scrolling,
  form filling, login, banner dismissal, stealth plugins or impersonating a
  normal browser UA. The identifying UA is supplied consistently. Timeout covers
  robots, launch, navigation, settling and serialization, reserving a bounded
  portion for teardown. No retry on failure. DOM size is capped in UTF-8 bytes;
  oversized results return too_large with no HTML/snapshot.
- Obvious title/text challenge phrases or captcha containers return
  blocked_by_site. HTTP 401/403 during navigation also stops. Do not dismiss,
  solve or bypass interstitials. Simple markers can have false positives/negatives.
  Rendering does not establish that visible claims are true or supported.

| Status | Meaning |
|---|---|
| ok | Allowed HTML DOM captured; may still be thin or incomplete |
| blocked | Initial/redirect path denied by robots; no target request |
| blocked_by_site | Site access denial or deterministic challenge marker; no workaround |
| timeout | Overall render budget exhausted |
| too_large | Captured UTF-8 HTML exceeds max_bytes |
| render_error | Invalid URL, host/limit violation, robots/network/browser or non-HTML navigation failure |
| unavailable | Optional Playwright/Chromium missing |

## Private snapshot provenance and drift

FetchResult.fetch_mode defaults to http. A successful fallback changes it to
rendered, replacing content/hash with captured DOM, clearing the old HTTP
snapshot_path and recording renderer versions, allow_hosts and block diagnostics.
snapshot_page stores **the rendered DOM**, not the initial HTTP body, as the raw
slug HTML and generates a fresh cleaned .txt. No frozen gold original is changed
by the helper. Existing private refetch path separation still applies.

SnapshotRecord and manifest schema add fetch_mode (default http), nullable
Playwright/browser versions and allow_hosts (default empty); old manifests remain
valid without these keys. Rendered records require HTML and both renderer versions;
HTTP/PDF records cannot claim renderer metadata. Mode, renderer-version or allow
list changes take precedence over raw equality as tool_version_changed, retaining
cleaned_text_changed. Owner review/re-baselining remains deliberate, with no
automatic --adopt. DOM bytes can vary despite equal tool versions/fixed settling;
no deterministic real-site rendering or content accuracy is promised.

Refetch reports rendering statuses/blocked hosts, preserves baseline entries on
failure and keeps the existing table/exit semantics (reported source/render
failures exit 0; script/configuration errors exit 1). No force flag exists.

## Terms, tests and CI

**Rendering does not change what source terms allow.** Consult
[source-terms.md](source-terms.md), risk R4/R11 and ADR 007. robots permission is
necessary, not legal permission. Explicitly allowing hosts is the user's deliberate
per-source decision, not an agent-inferred workaround. Snapshots/page contents
must never be committed; eval/gold and frozen snapshots are unchanged.

Browser tests are marked browser and use a server bound only to 127.0.0.1, with
localhost as the second exact hostname for opt-in tests. There are no live sites,
LLM calls, keys or real pages. They skip with installation instructions when the
optional package/browser is missing; non-browser unit tests always run.
The existing quality job is unchanged. A separate render-tests job installs
.[render,test] and Chromium and runs only browser-marked tests. It uses job-level
continue-on-error: true and is advisory; no new required check or branch-protection
rule is configured by this PR. Read its job result even when the workflow is green.
