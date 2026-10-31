# ADR 017 — Restricted optional rendering and reproducible snapshot provenance

**Status:** Accepted · **Date:** 2026-10-31

## Context

ADR 006 reserves browser cost for insufficient static text; source-terms review
and private snapshots remain required by ADR 007. The owner explicitly removed
force-render overrides and retained the fetcher's exact-host redirect policy.
Rendered DOM and HTTP source are different inputs, even if their hashes coincide.

## Decision

Keep Fetcher.fetch plain HTTP and run_pipeline local. An explicit prepare_page
step may invoke an optional lazily loaded Playwright renderer **only** when
successful HTTP HTML is suspiciously_empty under the existing cleaner diagnostic.
No alternate trigger, force flag or PDF rendering. Preserve failures explicitly.

Use the fetcher's robots classification/cache/path checks through cancellable
asynchronous I/O before launch and each permitted request, the same identifying
UA, per-host pacing and crawl-delay. Do not follow robots redirects or infer
permission on errors. Limit main navigation to the same hostname and five hops,
including script/meta changes. Any hostname change is render_error with reason
redirect_host_change, regardless of subresource permissions.

Default subresources to the page's exact hostname; abort images/media/fonts,
block service workers/downloads and close WebSockets. Other hosts require an
explicit exact allow_hosts tuple (repeatable CLI --allow-host), never inference
or wildcards. Record sorted/deduplicated allow_hosts in snapshot metadata.
Record aborted count plus sorted distinct other-host names, capped at 20, without
URLs/query strings. Restricted resource-redirect fulfillment is not a promise of
unrestricted browser fidelity.

Wait for load plus a fixed settle delay, cap UTF-8 DOM bytes, and bound the whole
attempt including robots/launch/teardown. Never interact with banners, forms,
challenges or logins; no stealth, impersonation or retry. Obvious bot walls return
blocked_by_site and stop. An allowed-host decision cannot relax robots or main
navigation rules and remains the owner's source-terms decision.

Store rendered DOM as private raw HTML with fetch_mode, Playwright/browser
versions and allow_hosts. Missing metadata means legacy http. Mode, renderer
versions or allow_hosts changes are tool_version_changed before raw hash equality
(ADR 015), with cleaned_text_changed preserved. No gold/snapshot migration or
automatic baseline adoption. Frozen DOM can be processed locally with existing
extraction tooling, without another browser.

## Consequences

The heuristic can miss small JS shells and pages with large navigation but little
content. A future trigger amendment needs evidence from real pages; none is
collected here. Explicitly blocked hosts explain some thin renders, but missing
content, changing sites, incomplete settling and challenge-marker mistakes remain.
Rendering grants no snapshot publication permission or truth/support guarantee.
The optional browser CI job is advisory; core checks/imports remain independent
of Playwright. See [doc 19](../19-rendering-fallback.md).
