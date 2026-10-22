# ADR 011 — Deterministic passage IDs and bounded segmentation

**Status:** Accepted · **Date:** 2026-10-22

## Context

The extractor and verifier need document-local passage identities and traceable offsets without copies that drift from cleaned source text. Real cleaner output includes consecutive headings and long table rows, so a soft character target alone cannot preserve structure. Page content may contain prompt injection; segmentation must never interpret it or imply verification (ADR 003/008/010).

## Decision

Use frozen dataclasses and a shared immutable source string. Passage.text is a property slicing document text, not a stored substring. Preserve document text, half-open character ranges and clipped references to existing HTML/PDF maps. Hash whitespace-normalized passage text with SHA-256, retain the first eight lowercase hex characters, and prefix the zero-based index: `p{index:04d}-{text_hash}`. Store `SEGMENTER_VERSION="1"`; changing **any rule** requires a bump.

Apply this precedence explicitly:

1. Handle invalid limits and unsupported/empty sources first. PDF page changes force new passages. Identify HTML rows by `tr` source paths before heading detection inside a row. Short `h1`–`h6` heading lines start structural blocks; heading lines longer than max_chars are ordinary lines.
2. Keep consecutive short headings plus their first following content line together, above the soft limit if necessary.
3. Enforce `hard_max = 2 * max_chars`. Oversized heading blocks break on heading boundaries, including after the last heading before content. Only this overflow case (or a final source heading) allows a heading alone at the end of a passage.
4. Keep a table row whole through hard_max. Beyond it, split only at generated ` | ` cell delimiters; cells above hard_max use ordinary-line splitting. Retain delimiters, including bounded standalone fragments if needed; never confuse literal cell text with a generated delimiter.
5. Split oversized ordinary content at sentence ends, then whitespace; never inside a word. A single unbreakable word is kept whole and alone even above hard_max. Greedily combine bounded units to the soft limit while respecting structural starts and page boundaries.

**Invariant:** every passage length is at most hard_max, except a single unbreakable word. Set exceeds_max when length exceeds the soft max_chars. Preserve every non-whitespace character exactly once, with only whitespace gaps. No rewriting, rewrapping, de-hyphenation or interior trimming is allowed. Heading metadata uses the latest short structural heading line, including the last heading of a run; PDFs have no heading metadata.

Exact quote lookup returns document-global offsets for the first occurrence within the named passage; absent/non-exact matches return None. It performs no fuzzy matching or evidence verification. Full details and source-reference conventions are in [the segmenter contract](../12-segmenter.md).

## Consequences

Same input/maps/configuration produces the same passages and IDs without clocks, locale or randomness. Repeated text is distinguishable by index. Appending a paragraph preserves all earlier IDs except possibly the last. Earlier edits, structural/configuration changes and version bumps can change subsequent IDs; short hashes are not global identifiers, and unchanged hashes do not guarantee unchanged offsets. Cache/replay must include source identity, transformation versions and configuration.

The approved ceiling exceptions preserve useful structure while bounding output. References remain traceable, but page text stays untrusted and no field is promoted to verified. LLM handling belongs to #19 and actual verification/fuzzy matching to #20. Tests contain only synthetic/generated sources, with seeded property-style coverage tests when Hypothesis is unavailable.
