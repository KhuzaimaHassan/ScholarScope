# HTML cleaner and source offsets

`scholarscope.cleaner.clean_html(html: bytes | str) -> CleanedHTML` extracts static HTML text for the future segmenter. It performs no network requests or file writes.

BeautifulSoup with the `lxml` parser provides malformed-HTML recovery and a traversable DOM. Both libraries are declared in `pyproject.toml` and installed by CI. Byte input uses the parser's encoding detection, including declared HTML encodings; string input keeps its Unicode text.

## Extraction

The cleaner selects visible `<main>` / `role="main"` containers, or falls back to the body/document when none exists. Nested main containers are traversed once. If the combined selected main text is **shorter than 500 characters AND less than 30% of the body text length**, the cleaner falls back to the body to avoid losing content outside a fragmentary main. Both lengths use whitespace-normalized text after the same noise filtering; excluded navigation, controls and hidden content do not inflate the comparison. The boundaries are strict: exactly 500 characters or exactly 30% keeps main. An empty main falls back when body has content. It preserves DOM order and original wording without translating, summarizing, or adding bullet numbers.

Navigation, footer, head, script, style, noscript and template subtrees are excluded. Exception: a `<nav>` or `role="navigation"` wrapper containing main content is traversable, but only its visible `<main>` / `role="main"` descendants are rendered. Its surrounding menu text remains excluded, including during body fallback. Hidden ancestors and other exclusion rules still apply. This handles main content nested in navigation shells by unusual or malformed markup without retaining the menu. A page-level `<header>` banner is excluded, while headers inside `<main>`, `<article>`, `<section>` or `role="main"` are kept, including their headings. Contentinfo roles remain excluded; a content header's explicit banner role does not override its content context. Hidden attributes, `aria-hidden="true"` and inline CSS hiding are recognized. Cookie banners are identified by specific ID/class markers and cookie-labeled dialogs; ordinary text mentioning cookies is retained.

Forms are content containers, not blanket exclusions: an ASP.NET-style `<form runat="server">` wrapping the page keeps its eligibility prose, headings and source offsets. Native controls (`input`, `select`, `textarea`, `button`, `datalist`, options and `output`) are excluded. Custom interactive widgets without ARIA labels or a wrapping label are excluded. Forms with `role="search"`, clear search/login identifiers (ID, name, class, action or ARIA label), or a short bare search/login UI label are excluded. A paragraph merely mentioning search is retained.

Headings, paragraphs and list items remain in the output, separated by line breaks. Inline text retains source spacing and punctuation after whitespace normalization. Table rows become lines with ` | ` between cells; empty cells preserve column delimiters. Blocks inside a cell are joined with spaces. `<pre>` retains normalized line breaks while collapsing repeated spaces/tabs. Empty input produces empty text and an empty map.

## Offset contract

`CleanedHTML` contains `text`, an ordered tuple `offset_map`, `title: str | None`, `root_used: Literal["main", "body"]`, and `suspiciously_empty: bool` (default `False`). The diagnostic is `True` exactly when the input is larger than 5,000 bytes and the final cleaned text has fewer than 200 Python characters. String input size is its UTF-8 byte length; byte input size is its original byte length. The boundaries are strict (5,000 bytes or 200 output characters does not trigger it). This is a heuristic warning, not proof of a blocked/empty page, and does not change extraction, offsets, or root selection. Callers should investigate flagged results rather than silently accepting them.

`root_used` identifies the actual selection, including a fragment-main fallback; `body` also covers document fallback for an empty/body-less parse. The document `<title>` is retained separately as entity-decoded, whitespace-normalized metadata, or `None` when absent/blank. It is not appended to `text` and has no entries in `offset_map`. Each immutable `SourceSpan` has:

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

The private Twente pilot snapshot exposed the blanket navigation-subtree rule: the parsed chain was `html[class="utwente--ws2026 menuwide"] > body > nav[class="header-dest current"] > div[class="menucontainer"] > main[class="page-main"]`. `_ignored` excluded the `nav`, preventing main selection and then removing the content during body extraction. Regression fixtures reproduce this wrapper structure with small fictional markup, not copied page content. They also check menu exclusion during fallback, hidden ancestors, and the low-output diagnostic thresholds for bytes and strings.

Tests contain 18 base synthetic HTML fixtures, exercised as strings and bytes, plus offset round-trip, repeated-text, declared-encoding and empty-output checks. They cover navigation/footer noise, tables, nested lists, hidden elements, entities, body fallback, empty and malformed HTML, PDF-like `<pre>` content and non-English text. Regression tests also cover ASP.NET wrapping forms, controls versus search/login forms, contextual headers, separate title metadata, strict fragment-main thresholds in both directions, body-fallback source offsets and navigation-excluded length comparisons. No real page contents or snapshots are committed, and `eval/gold/` is unchanged.
