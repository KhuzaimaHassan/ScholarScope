# PDF text extraction

`scholarscope.pdf_text.extract_pdf_text(data: bytes) -> ExtractedPDF` extracts PDF text in memory. It performs no network requests or file writes. **pypdf** is the runtime dependency: its per-page layout mode keeps straightforward table cells on the same row and exposes physical page boundaries. **ReportLab** is a test-only dependency in the `test` extra and CI; fixtures generate fictional PDFs/images entirely in memory.

## Output and offsets

| Field | Meaning |
|---|---|
| `text` | Normalized page text joined with two newlines between nonempty pages |
| `pages` | Immutable `PDFPage(page_number, text)` records; physical page numbers are 1-based, including blank pages |
| `offset_map` | Immutable `PDFTextSpan(start, end, page_number, page_start, page_end, is_separator)` records |
| `status` | `ok`, `scanned_unsupported`, `encrypted_unsupported`, or `invalid` |
| `page_count` | Parsed physical page count; zero when unavailable, or for a zero-page PDF |

All ranges are half-open Python character offsets in **normalized text**, not PDF bytes or page coordinates. A source span satisfies `result.text[start:end] == result.pages[page_number - 1].text[page_start:page_end]`. Subranges within it translate by adding the same character displacement.

The map covers all output characters. Inserted page separators have `is_separator=True` and a zero-width source range at the preceding nonempty page's end; they are formatting, not quoted characters. Blank pages retain their original page numbers without introducing text.

Use `result.locator(offset)` or `locator(result, offset)` for a physical-page citation such as `p.3`. Separators belong to the preceding text page; invalid/out-of-range offsets return `None`. Specific labels such as `p.3, table 2` still need the owner's table identification.

## Outcomes and limits

- `ok`: text is available. Layout whitespace is normalized per line and empty lines removed. Extracted wording, language and printed hyphenation remain unchanged; there is no de-hyphenation, translation or OCR.
- `scanned_unsupported`: fewer than **25 non-whitespace characters per physical page on average**, including blank/zero-page PDFs. Aggregate text, per-page text and offsets are cleared; known page numbers/count remain. This heuristic can reject genuinely sparse text PDFs. A text-rich mixed document may still contain image-only pages despite an overall `ok` result.
- `encrypted_unsupported`: a nonempty password or unavailable decryption support is required. No text is exposed; the page count is normally unavailable. Encryption accepting an empty password is supported.
- `invalid`: strict parsing or extraction fails, or a page's `/Contents` is not a stream/array of streams (missing/null content is a valid blank page). This explicit type check avoids dependency-version differences that silently treat malformed contents as blank. Data-related parser/codec exceptions do not escape, and no partial text/offsets are exposed; a page count already parsed may remain available.

Complex tables, columns, rotation and missing font mappings can affect reading order and text fidelity. Layout extraction is not semantic table recognition. Repeated extraction of identical bytes is deterministic within the same library environment; dependency upgrades require rechecking extraction. This module does not replace the labeling guide's existing hand-saved text workflow or create gold labels.
