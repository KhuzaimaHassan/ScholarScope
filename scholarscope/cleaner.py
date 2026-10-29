"""Deterministic static HTML extraction with offsets into the original parsed DOM.

Source offsets are half-open Python character indices in entity-decoded DOM text
nodes, not raw HTML bytes. Paths are indexed before filtering, so removing noise
never renumbers a retained node. Structural separators have a source element path
and None source offsets; they are formatting, not quoted evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Literal
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction
from bs4.element import PageElement, Tag

# Bump whenever extraction behavior changes; snapshot hashes depend on these rules.
CLEANER_VERSION = "2"

_REMOVED_TAGS = frozenset(
    {
        "nav",
        "footer",
        "head",
        "script",
        "style",
        "noscript",
        "template",
        "input",
        "select",
        "textarea",
        "button",
        "datalist",
        "option",
        "optgroup",
        "output",
    }
)
_REMOVED_ROLES = frozenset({"navigation", "banner", "contentinfo"})
_WIDGET_ROLES = frozenset(
    {
        "button",
        "checkbox",
        "combobox",
        "listbox",
        "option",
        "radio",
        "scrollbar",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "textbox",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
    }
)
_CONTENT_CONTAINERS = frozenset({"main", "article", "section"})
_FORM_MARKERS = frozenset({"search", "searchform", "login", "loginform", "signin", "signinform"})
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
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
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
    """Map text[start:end] to original DOM text, layout, or synthetic link metadata.

    Text paths end in /text()[n]. For text spans, normalizing the whitespace in
    the node's source_start:source_end slice recovers the output span. For layout
    spans, both source indices are None and node_path identifies the element
    responsible for the line break or table delimiter. Synthetic URL suffixes
    instead have is_synthetic=True, null source indices and the anchor's path;
    they are not separators and never pretend to be original DOM text.
    """

    start: int
    end: int
    node_path: str
    source_start: int | None
    source_end: int | None
    is_synthetic: bool = False

    def __post_init__(self) -> None:
        if self.is_synthetic and (self.source_start is not None or self.source_end is not None):
            raise ValueError("synthetic spans have no DOM text offsets")

    @property
    def is_separator(self) -> bool:
        return self.source_start is None and not self.is_synthetic


@dataclass(frozen=True)
class CleanedHTML:
    """Offset-mapped text, document metadata, and a low-output diagnostic."""

    text: str
    offset_map: tuple[SourceSpan, ...]
    title: str | None = None
    root_used: Literal["main", "body"] = "body"
    suspiciously_empty: bool = False


@dataclass(frozen=True)
class _Piece:
    text: str
    node_path: str
    source_start: int | None = None
    source_end: int | None = None
    is_synthetic: bool = False


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
                SourceSpan(
                    position,
                    end,
                    piece.node_path,
                    piece.source_start,
                    piece.source_end,
                    piece.is_synthetic,
                )
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


def _marker_words(value: str) -> list[str]:
    dashed = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", value).lower()
    return re.findall(r"[a-z0-9]+", dashed)


def _is_search_or_login_form(node: Tag, roles: list[str]) -> bool:
    if "search" in roles:
        return True
    markers = [str(node.get(name, "")) for name in ("id", "name", "action", "aria-label")]
    markers.extend(value or "" for value in node.get_attribute_list("class"))
    for marker in markers:
        words = _marker_words(marker)
        if _FORM_MARKERS.intersection(words):
            return True
        if any(pair in {("log", "in"), ("sign", "in")} for pair in pairwise(words)):
            return True
    # Recognize a bare search/login UI without treating prose mentioning search as a marker.
    label = " ".join(node.get_text(" ", strip=True).lower().split())
    return (
        re.fullmatch(r"(?:search|log[ -]?in|sign[ -]?in)(?: (?:go|submit|search))?", label)
        is not None
    )


def _is_main(node: Tag) -> bool:
    return node.name == "main" or "main" in str(node.get("role", "")).lower().split()


def _is_navigation(node: Tag) -> bool:
    return node.name == "nav" or "navigation" in str(node.get("role", "")).lower().split()


def _ignored(node: Tag) -> bool:
    roles = str(node.get("role", "")).lower().split()
    content_header = node.name == "header" and any(
        isinstance(parent, Tag)
        and (
            parent.name in _CONTENT_CONTAINERS
            or "main" in str(parent.get("role", "")).lower().split()
        )
        for parent in node.parents
    )
    removed_roles = _REMOVED_ROLES.difference({"banner"}) if content_header else _REMOVED_ROLES
    # Malformed/unusual layouts can nest main content in a navigation shell.
    # Keep the shell traversable; _render keeps only its visible main descendants.
    navigation_wrapper = _is_navigation(node) and any(
        isinstance(child, Tag) and _is_main(child) for child in node.find_all(True)
    )
    if navigation_wrapper:
        removed_roles = removed_roles.difference({"navigation"})
    if (
        node.name in _REMOVED_TAGS and not (node.name == "nav" and navigation_wrapper)
    ) or removed_roles.intersection(roles):
        return True
    if node.name == "header" and not content_header:
        return True
    if node.name == "form" and _is_search_or_login_form(node, roles):
        return True
    if _WIDGET_ROLES.intersection(roles) and not (
        str(node.get("aria-label") or "").strip()
        or str(node.get("aria-labelledby") or "").strip()
        or node.find_parent("label") is not None
    ):
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


def _main_roots(container: Tag) -> list[Tag]:
    mains = [
        node
        for node in container.find_all(True)
        if isinstance(node, Tag)
        and _is_main(node)
        and not any(_ignored(parent) for parent in (node, *node.parents) if isinstance(parent, Tag))
    ]
    main_ids = {id(node) for node in mains}
    return [node for node in mains if not any(id(parent) in main_ids for parent in node.parents)]


def _render(
    node: PageElement,
    builder: _TextBuilder,
    paths: dict[int, str],
    *,
    inline: bool = False,
    preformatted: bool = False,
    base_url: str | None = None,
) -> None:
    if _is_text(node):
        builder.text(str(node), paths[id(node)], preformatted=preformatted)
        return
    if not isinstance(node, Tag) or _ignored(node):
        return
    if _is_navigation(node):
        for main in _main_roots(node):
            _render(
                main, builder, paths, inline=inline, preformatted=preformatted, base_url=base_url
            )
        return
    path = paths.get(id(node), "")
    anchor_start = len(builder.pieces)
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
            _render(cell, cell_builder, paths, inline=True, base_url=base_url)
            builder.extend(cell_builder.pieces)
    else:
        for child in node.children:
            _render(
                child,
                builder,
                paths,
                inline=inline,
                preformatted=preformatted or node.name == "pre",
                base_url=base_url,
            )
    if node.name == "a" and node.has_attr("href"):
        label = "".join(piece.text for piece in builder.pieces[anchor_start:]).strip()
        target = _link_target(str(node.get("href", "")), base_url)
        if (
            label
            and target is not None
            and label
            not in {
                target,
                target.split("://", 1)[1],
                target.split(":", 1)[1],
            }
        ):
            # Insert before pending source whitespace, retaining it after the URL.
            pending, builder.pending = builder.pending, None
            builder.extend([_Piece(f" ({target})", path, is_synthetic=True)])
            builder.pending = pending
    if is_block:
        builder.boundary(path, inline=inline)


def _link_target(href: str, base_url: str | None) -> str | None:
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    try:
        parsed = urlsplit(href)
        if parsed.scheme:
            return href if parsed.scheme in {"http", "https"} and parsed.netloc else None
        if base_url is None:
            return None
        target = urljoin(base_url, href)
        parsed = urlsplit(target)
        return target if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None  # Invalid URL markup is not repaired or fetched.


def _extract(roots: list[Tag], paths: dict[int, str], base_url: str | None) -> CleanedHTML:
    builder = _TextBuilder()
    for root in roots:
        builder.boundary(paths.get(id(root), ""), inline=False)
        _render(root, builder, paths, base_url=base_url)
    return builder.finish()


def clean_html(html: bytes | str, *, base_url: str | None = None) -> CleanedHTML:
    """Extract visible main text without rewriting wording or translating it.

    Prefer visible main/role=main containers, otherwise use body/document. A main
    fragment shorter than 500 normalized characters and 30% of cleaned body text
    also falls back to body. The document title is metadata, outside text offsets. All
    visibility checks are static (attributes and inline CSS); external stylesheets
    and JavaScript are not executed. Bytes use the parser's encoding detection.
    Text stays in DOM order. Paragraphs, headings and list items have line breaks;
    table rows have cell delimiters, and pre blocks retain normalized line breaks.
    Retained anchor text gets a synthetic HTTP(S) target suffix. Explicit base_url
    enables relative resolution (HTML base href wins); None skips relative links.
    Synthetic URLs do not affect the existing fragment-main length comparison.
    """

    soup = BeautifulSoup(html, "lxml")
    # None deliberately disables relative resolution, even with an HTML base.
    # An explicit invalid/non-HTTP base disables relative links, never guesses.
    effective_base = _link_target(base_url, None) if base_url is not None else None
    base_node = soup.find("base", href=True)
    if base_url is not None and isinstance(base_node, Tag):
        html_base = str(base_node.get("href", "")).strip()
        resolved = _link_target(html_base, None)
        if resolved is None and effective_base is not None:
            resolved = _link_target(urljoin(effective_base, html_base), None)
        effective_base = resolved
    title_node = soup.title
    title = (" ".join(title_node.get_text().split()) or None) if title_node is not None else None
    paths: dict[int, str] = {}
    _index_nodes(soup, paths)
    roots = _main_roots(soup)
    body = soup.body or soup
    root_used: Literal["main", "body"] = "body"
    if not roots:
        result = _extract([body], paths, effective_base)
    else:
        result = _extract(roots, paths, effective_base)
        root_used = "main"
        main_length = _visible_length(result)
        if main_length < 500:
            body_result = _extract([body], paths, effective_base)
            body_length = _visible_length(body_result)
            if main_length * 10 < body_length * 3:
                result = body_result
                root_used = "body"
    input_bytes = len(html) if isinstance(html, bytes) else len(html.encode("utf-8"))
    return replace(
        result,
        title=title,
        root_used=root_used,
        suspiciously_empty=input_bytes > 5_000 and len(result.text) < 200,
    )


def _visible_length(result: CleanedHTML) -> int:
    # Link metadata must not change the existing fragment-main selection rule.
    visible = "".join(result.text[s.start : s.end] for s in result.offset_map if not s.is_synthetic)
    return len(" ".join(visible.split()))
