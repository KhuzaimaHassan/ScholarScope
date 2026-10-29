# ADR 015 — Link targets in cleaned text and honest synthetic provenance

**Status:** Accepted · **Date:** 2026-10-29

## Context

The literal URL-provenance guard in ADR 014 rejects genuine application links
when only anchor labels reach extraction. Preserve source targets without asking
the model to invent them or weakening that guard. A resolved URL is derived
metadata, not an original DOM text-node substring; source maps must say so.

## Decision

Cleaner version 2 renders retained nonempty anchor labels as `label (absolute_url)`
for HTTP(S) targets. Skip empty/fragment-only hrefs and other schemes. Suppress
the suffix if the stripped label already equals the target or its scheme-less
form. Preserve target casing, query, fragment and percent spelling after normal
DOM attribute entity decoding/outer whitespace trimming; do not fetch or strip
tracking data. An explicit base_url enables relative resolution; the first HTML
base href wins, otherwise use fetch final_url (fall back to original URL). None
skips relative targets. Hidden/excluded content and visibility rules are unchanged.
Synthetic metadata is excluded from fragment-main length comparisons.

Extend SourceSpan minimally with is_synthetic (default False). Synthetic suffixes
have null DOM offsets, the anchor element path, and are distinct from layout
separators. Preserve this flag when clipping references. Original source ranges,
full cleaner coverage, exact passage slicing and ordered/non-overlapping offsets
are unchanged. The verifier reports document-global matched offsets plus clipped
source_refs and locator; overlapping synthetic text points to the anchor, never
invented DOM character positions. Input evidence/citations stay unchanged.
Matching and segmentation rules remain unchanged, with their version constants 1.

The scan/provenance guard run unchanged over enriched text. Existing prompts need
no new instruction or version bump. Verified presence includes explicitly marked
derived text, not a claim of visible DOM prose, value support, truth or URL safety.

For snapshot drift, tool versions take precedence over raw hashes. Return both
classification and cleaned_text_changed; a harmless-output version bump still
reports tool_version_changed. Keep the refetch table and exit codes unchanged.
After review the owner deliberately re-baselines; --adopt is deferred until labels
exist and is not implemented here. No labels/private snapshots are migrated.

## Consequences

Href-only targets can reach extraction and satisfy literal provenance with honest
anchor locations. Different derived text can change hashes, offsets and passage
IDs even for identical raw bytes. Missing base context, excluded/empty anchors,
unsupported schemes, omitted passages and scheme-less deduplication remain
conservative recall limits. False/hostile source content can still verify; this
does not change ADR 003/012/014's residual risks. Tests use fictional HTML, temporary
synthetic snapshots and FakeClient; no live fetch/provider calls or new dependency.
