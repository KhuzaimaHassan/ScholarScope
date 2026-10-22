# Stable passages and source references (version 1)

`segment(source: CleanedHTML | ExtractedPDF, *, max_chars=1200) -> SegmentedDocument` makes deterministic passages from the existing cleaner/PDF output. It never fetches pages, calls an LLM, or interprets page instructions. All passage text is **untrusted source data**, not instructions. No verification or eligibility status is produced.

## Output and offsets

The output uses frozen dataclasses. `SegmentedDocument` holds the unchanged `text`, tuple of passages, `segmenter_version="1"`, source kind (`html`/`pdf`), and optional unsupported reason. Every Passage references the **same immutable full-text string**, not a stored copy of its substring. Its read-only `text` property slices `[start:end]`; document construction rejects passages bound to another string. Normal mutation is prohibited.

Each passage has `id`, zero-based `index`, half-open Python character `start`/`end`, eight-character lowercase `text_hash`, optional `section_heading`, optional `locator`, source-reference tuple and `exceeds_max = (end - start > max_chars)`. All content is an exact slice; no rewriting, translation, rewrapping, de-hyphenation or interior trimming occurs. Whitespace-only gaps between slices are permitted; every non-whitespace character is covered exactly once, in source order without overlaps.

Source references reuse the existing immutable `SourceSpan` / `PDFTextSpan` types, clipped to their overlap with the passage. Their `start`/`end` remain document-global; HTML paths and source offsets remain entity-decoded DOM coordinates. A collapsed whitespace character retains its full original raw source range. Generated HTML separators retain null source indices, and PDF page separators retain their zero-width page ranges and separator flag: neither becomes quoted page evidence. PDF text references use one-based physical pages and per-page character ranges. No original maps are mutated or renumbered.

HTML's locator is the first referenced node path. PDF locators are `p.N` or `p.N-M` from non-separator page references; with ordinary extractor output, forced page boundaries mean each passage normally has a single-page locator. `section_heading` is the most recent short structural heading line, or the last heading in its consecutive run. It is null for PDFs. A long heading treated as ordinary text does not replace this metadata.

## Explicit precedence and ceiling

1. Reject `max_chars < 50`. For an unsupported PDF status or empty/whitespace-only text, return unchanged document text, no passages and an unsupported reason. A non-`ok` PDF takes precedence over empty text when choosing that reason.
2. Work on cleaned newline-delimited lines; preserve their original spans. PDF page changes force new passages. HTML rows are identified by a `tr` element in overlapping node paths; row classification takes precedence over headings embedded inside cells. Other `h1`–`h6` paths identify heading lines. A heading longer than `max_chars` is ordinary content for segmentation.
3. Consecutive short headings plus the first following content line form one atomic heading block, allowed above the soft limit. It starts a new passage. With no following content, the final heading/run remains intact where possible.
4. **`hard_max = 2 * max_chars`.** If a heading block would exceed it, break at heading boundaries (including after the last heading, before following content) into bounded groups. A heading can end a passage without its content only in this overflow case, or when it is the last source line. Detached content follows its ordinary/table rules. Group headings left to right up to the hard ceiling, attaching the first content line to the final group only if it fits.
5. A table row of at most `hard_max` characters stays whole, even above `max_chars`. A longer row splits at cleaner-generated ` | ` cell separators, never at a literal pipe inside a cell. Cells remain whole unless the cell itself exceeds `hard_max`; that cell uses ordinary-line splitting. Retain every pipe: delimiters attach to an adjacent bounded fragment where possible, or can form a separate fragment when necessary. Row fragments remain bounded.
6. Oversized ordinary lines (including long headings and oversized cells) split at the last sentence ending within the limit (`. `, `? `, `! `, `; `), otherwise at the last whitespace before the limit. If that would split a word, keep that word whole. No word, Unicode character or combining sequence is cut internally. Boundary whitespace may remain in gaps, but interior whitespace is unchanged.
7. Greedily combine units left to right up to `max_chars`, honoring heading starts and PDF page boundaries. Heading/table units can exceed the soft limit, but **every passage length is at most `hard_max`, except a single unbreakable word**. An oversized word is alone, with no adjacent content or whitespace added. Tests enforce this invariant, including exact-ceiling and one-character overflow cases.

The original line-never-split rule has only the approved ordinary-line and hard-ceiling exceptions above. Grouping and lookup use ordered source offsets, not dictionary iteration, clocks, locale or randomness.

## IDs and stability

`text_hash = sha256(" ".join(passage.text.split()).encode("utf-8")).hexdigest()[:8]`, then `id = f"p{index:04d}-{text_hash}"`. Whitespace collapsing/stripping is **only for the hash**, never for stored document text or passage offsets. Repeated identical text gets distinct IDs through its index. These are document-local IDs, not globally unique cryptographic identifiers or proof of unchanged evidence.

`SEGMENTER_VERSION` starts at `"1"`. **Changing any segmentation, precedence, boundary or ID rule requires a version bump.** Reproducibility also requires the same source text/maps and `max_chars`; cache keys should include source identity, cleaner/PDF version, segmenter version and configuration, not just the short hash.

Appending a paragraph at the end preserves existing passage IDs except possibly the last passage, which may grow or be regrouped. Edits or insertions earlier in the document, changed structure, changed configuration, or a version bump can change boundaries and all subsequent indexed IDs. Whitespace-only edits can leave hashes unchanged while offsets change; always recompute source references. No cross-edit/global anchor stability is promised.

## Exact lookup and deferred work

`passage_by_id(doc, passage_id)` returns the passage or None. `locate(doc, passage_id, quote)` returns **document-global** half-open offsets of the first exact occurrence within that passage, or None for missing IDs, empty/missing quotes or non-exact matches. Repeated quotes use the first occurrence, not guessed disambiguation. No normalization or fuzzy matching is done by locate.

LLM prompts/calls and safe treatment of passage data remain #19. Evidence presence verification, normalized fuzzy matching, support audits and verification-state transitions remain #20 (ADR 003/008/010). Source-reference availability never means evidence is verified. This issue adds no labels, source snapshots, network calls or decision logic.

Tests use synthetic HTML through `clean_html`, generated in-memory ReportLab PDFs via the existing helpers, and 100 deterministic seeded random line sets. Hypothesis was not installed locally, so no dependency download or test dependency/CI change was made.
