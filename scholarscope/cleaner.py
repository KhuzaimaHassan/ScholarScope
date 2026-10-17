"""Deterministic static HTML extraction with offsets into the original parsed DOM.

Source offsets are half-open Python character indices in entity-decoded DOM text
nodes, not raw HTML bytes. Paths are indexed before filtering, so removing noise
never renumbers a retained node. Structural separators have a source element path
and None source offsets; they are formatting, not quoted evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction
from bs4.element import PageElement, Tag

_REMOVED_TAGS = frozenset(
    {"nav", "header", "footer", "head", "script", "style", "form", "noscript", "template"}
)
_REMOVED_ROLES = frozenset({"navigation", "banner", "contentinfo"})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "caption",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_COOKIE_MARKERS = (
    "cookie-banner",
    "cookies-banner",
    "cookie-consent",
    "cookie-notice",
    "cookie-popup",
    "onetrust-banner-sdk",
    "onetrust-consent-sdk",
    "cybot-cookiebot-dialog",
)
_NON_TEXT = (Comment, Declaration, Doctype, ProcessingInstruction)


@dataclass(frozen=True)
class SourceSpan:
    """Map text[start:end] to one DOM node (or a generated layout separator).

    Text paths end in /text()[n]. For text spans, normalizing the whitespace in
    the node's source_start:source_end slice recovers the output span. For layout
    spans, both source indices are None and node_path identifies the element
    responsible for the line break or table delimiter.
    """

    start: int
    end: int
    node_path: str
    source_start: int | None
    source_end: int | None

    @property
    def is_separator(self) -> bool:
        return self.source_start is None


@dataclass(frozen=True)
class CleanedHTML:
    """Plain text and a complete, ordered, non-overlapping offset map."""

    text: str
    offset_map: tuple[SourceSpan, ...]


@dataclass(frozen=True)
class _Piece:
    text: str
    node_path: str
    source_start: int | None = None
    source_end: int | None = None


class _TextBuilder:
    def __init__(self) -> None:
        self.pieces: list[_Piece] = []
        self.pending: _Piece | None = None

    def boundary(self, node_path: str, *, inline: bool) -> None:
        self._queue_space(_Piece(" " if inline else "\n", node_path))

    def _queue_space(self, piece: _Piece) -> None:
        if self.pending is None or (piece.text == "\n" and self.pending.text != "\n"):
            self.pending = piece

    def extend(self, pieces: list[_Piece]) -> None:
        if not pieces:
            return
        if self.pieces and self.pending is not None:
            self.pieces.append(self.pending)
        self.pending = None
        self.pieces.extend(pieces)

    def text(self, raw: str, node_path: str, *, preformatted: bool) -> None:
        for match in re.finditer(r"\s+|\S+", raw):
            value = match.group()
            piece = _Piece(value, node_path, match.start(), match.end())
            if value.isspace():
                space = "\n" if preformatted and ("\n" in value or "\r" in value) else " "
                self._queue_space(_Piece(space, node_path, match.start(), match.end()))
            else:
                self.extend([piece])

    def finish(self) -> CleanedHTML:
        spans: list[SourceSpan] = []
        position = 0
        for piece in self.pieces:
            end = position + len(piece.text)
            spans.append(
                SourceSpan(position, end, piece.node_path, piece.source_start, piece.source_end)
            )
            position = end
        return CleanedHTML("".join(piece.text for piece in self.pieces), tuple(spans))


def _is_text(node: PageElement) -> bool:
    return isinstance(node, NavigableString) and not isinstance(node, _NON_TEXT)


def _index_nodes(node: Tag, paths: dict[int, str], prefix: str = "") -> None:
    counts: dict[str, int] = {}
    text_index = 0
    for child in node.children:
        if isinstance(child, Tag):
            counts[child.name] = counts.get(child.name, 0) + 1
            path = f"{prefix}/{child.name}[{counts[child.name]}]"
            paths[id(child)] = path
            _index_nodes(child, paths, path)
        elif _is_text(child):
            text_index += 1
            paths[id(child)] = f"{prefix}/text()[{text_index}]"


def _ignored(node: Tag) -> bool:
    roles = str(node.get("role", "")).lower().split()
    if node.name in _REMOVED_TAGS or _REMOVED_ROLES.intersection(roles):
        return True
    if node.has_attr("hidden") or str(node.get("aria-hidden", "")).strip().lower() == "true":
        return True
    for declaration in str(node.get("style", "")).lower().split(";"):
        property_name, _, value = declaration.partition(":")
        value = value.split("!", 1)[0].strip()
        if (property_name.strip(), value) in {
            ("display", "none"),
            ("visibility", "hidden"),
            ("visibility", "collapse"),
            ("content-visibility", "hidden"),
        }:
            return True
    identities = [str(node.get("id", "")), *node.get_attribute_list("class")]
    for identity in identities:
        dashed = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", identity or "").lower()
        dashed = re.sub(r"[^a-z0-9]+", "-", dashed).strip("-")
        if any(f"-{marker}-" in f"-{dashed}-" for marker in _COOKIE_MARKERS):
            return True
    return bool(
        {"dialog", "alertdialog"}.intersection(roles)
        and "cookie" in str(node.get("aria-label", "")).lower()
    )


def _render(
    node: PageElement,
    builder: _TextBuilder,
    paths: dict[int, str],
    *,
    inline: bool = False,
    preformatted: bool = False,
) -> None:
    if _is_text(node):
        builder.text(str(node), paths[id(node)], preformatted=preformatted)
        return
    if not isinstance(node, Tag) or _ignored(node):
        return
    path = paths.get(id(node), "")
    if node.name == "br":
        builder.boundary(path, inline=inline)
        return
    is_block = node.name in _BLOCK_TAGS
    if is_block:
        builder.boundary(path, inline=inline)

    if node.name == "tr" and not inline:
        cells = [
            child
            for child in node.children
            if isinstance(child, Tag) and child.name in {"td", "th"} and not _ignored(child)
        ]
        for index, cell in enumerate(cells):
            if index:
                builder.extend([_Piece(" | ", path)])
            cell_builder = _TextBuilder()
            _render(cell, cell_builder, paths, inline=True)
            builder.extend(cell_builder.pieces)
    else:
        for child in node.children:
            _render(
                child,
                builder,
                paths,
                inline=inline,
                preformatted=preformatted or node.name == "pre",
            )
    if is_block:
        builder.boundary(path, inline=inline)


def clean_html(html: bytes | str) -> CleanedHTML:
    """Extract visible main text without rewriting wording or translating it.

    Prefer visible main/role=main containers, otherwise use body/document. All
    visibility checks are static (attributes and inline CSS); external stylesheets
    and JavaScript are not executed. Bytes use the parser's encoding detection.
    Text stays in DOM order. Paragraphs, headings and list items have line breaks;
    table rows have cell delimiters, and pre blocks retain normalized line breaks.
    """

    soup = BeautifulSoup(html, "lxml")
    paths: dict[int, str] = {}
    _index_nodes(soup, paths)
    mains = [
        node
        for node in soup.find_all(True)
        if isinstance(node, Tag)
        and (node.name == "main" or "main" in str(node.get("role", "")).lower().split())
        and not any(_ignored(parent) for parent in (node, *node.parents) if isinstance(parent, Tag))
    ]
    main_ids = {id(node) for node in mains}
    roots = [node for node in mains if not any(id(parent) in main_ids for parent in node.parents)]
    builder = _TextBuilder()
    for root in roots or [soup.body or soup]:
        builder.boundary(paths.get(id(root), ""), inline=False)
        _render(root, builder, paths)
    return builder.finish()
