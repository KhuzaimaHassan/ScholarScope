# HTML cleaner and source offsets

`scholarscope.cleaner.clean_html(html: bytes | str) -> CleanedHTML` extracts static HTML text for the future segmenter. It performs no network requests or file writes.

BeautifulSoup with the `lxml` parser provides malformed-HTML recovery and a traversable DOM. Both libraries are declared in `pyproject.toml` and installed by CI. Byte input uses the parser's encoding detection, including declared HTML encodings; string input keeps its Unicode text.

## Extraction

The cleaner selects visible `<main>` / `role="main"` containers, or falls back to the body/document when none exists. Nested main containers are traversed once. It preserves DOM order and original wording without translating, summarizing, or adding bullet numbers.

Navigation, header, footer, head, script, style, form, noscript and template subtrees are excluded. Equivalent navigation/banner/contentinfo roles are excluded too. Hidden attributes, `aria-hidden="true"` and inline CSS hiding are recognized. Cookie banners are identified by specific ID/class markers and cookie-labeled dialogs; ordinary text mentioning cookies is retained.

Headings, paragraphs and list items remain in the output, separated by line breaks. Inline text retains source spacing and punctuation after whitespace normalization. Table rows become lines with ` | ` between cells; empty cells preserve column delimiters. Blocks inside a cell are joined with spaces. `<pre>` retains normalized line breaks while collapsing repeated spaces/tabs. Empty input produces empty text and an empty map.

## Offset contract

`CleanedHTML` contains `text` and an ordered tuple `offset_map`. Each immutable `SourceSpan` has:

| Field | Meaning |
|---|---|
| `start`, `end` | Half-open Python character range in `CleanedHTML.text` |
| `node_path` | Absolute XPath-style path in the original parsed DOM, such as `/html[1]/body[1]/main[1]/p[2]/text()[2]` |
| `source_start`, `source_end` | Half-open character range in that entity-decoded text node |
| `is_separator` | True for generated layout separators; both source offsets are then `None` |

The map covers every output character exactly once, with no overlaps or gaps. Source paths are assigned before filtering, so hidden/removed siblings do not renumber retained nodes. Repeated text in different nodes has distinct paths. Source offsets refer to decoded DOM characters, **not HTML byte offsets** or entity spellings such as `&amp;`.

To trace a passage `[a:b]`, select spans where `span.start < b and span.end > a`. A source span identifies its original node and raw decoded character range; normalizing whitespace in that source slice recovers the cleaned span. Word spans preserve exact characters; collapsed whitespace runs retain their complete source range. This also supports passages that cross inline markup.

Line breaks and table delimiters inserted for layout point to the responsible element with `source_start = source_end = None`. They are formatting and must not be treated as quoted source characters. Whitespace retained from a text node has actual source offsets instead.

Parse the private original HTML with the same parser when resolving paths, especially for malformed markup where parser repairs define the DOM. The tests include an independent XPath round-trip for a valid synthetic document and checks that repeated text retains its original sibling positions.

## Scope and validation

This is static DOM extraction. It does not execute JavaScript or compute CSS from stylesheets; arbitrary site-specific cookie widgets can require additional markers. Browser rendering, PDF extraction, segmentation and gold labeling are separate issues.

Tests contain 18 hand-authored synthetic HTML fixtures, exercised as strings and bytes, plus offset round-trip, repeated-text, declared-encoding and empty-output checks. They cover navigation/footer noise, tables, nested lists, hidden elements, entities, body fallback, empty and malformed HTML, PDF-like `<pre>` content and non-English text. No real page contents or snapshots are committed, and `eval/gold/` is unchanged.
