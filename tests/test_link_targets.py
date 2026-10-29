"""Fictional HTML/metadata only; no network, real pages, labels or snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from lxml import etree
from test_extractor import TITLE, fetch, field, payload

from scholarscope.cleaner import CLEANER_VERSION, SourceSpan, clean_html
from scholarscope.llm.base import StructuredRequest
from scholarscope.llm.fake import FakeClient
from scholarscope.pipeline import run_pipeline
from scholarscope.segmenter import segment, source_refs_for_range
from scholarscope.snapshots import classify_drift, snapshot_page

URL = "https://example.org/apply"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("network/DNS forbidden in link-target tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.mark.parametrize(
    "href,base,expected",
    [
        (URL, None, URL),
        ("HTTPS://Example.org/%2FApply?q=One#Two", None, "HTTPS://Example.org/%2FApply?q=One#Two"),
        ("/apply", "https://example.org/path/page", URL),
        ("apply", "https://example.org/awards/index", "https://example.org/awards/apply"),
        ("../apply?q=a%2Fb#terms", "https://example.org/path/page", URL + "?q=a%2Fb#terms"),
        (
            "//other.example.org/apply",
            "https://example.org/page",
            "https://other.example.org/apply",
        ),
        ("?q=A%2Fb#terms", "https://example.org/page", "https://example.org/page?q=A%2Fb#terms"),
        ("/apply", None, None),
        ("apply", None, None),
    ],
)
def test_absolute_relative_and_verbatim_targets(
    href: str, base: str | None, expected: str | None
) -> None:
    result = clean_html(f'<p><a href="{href}">Apply now</a></p>', base_url=base)
    assert result.text == (f"Apply now ({expected})" if expected else "Apply now")
    synthetic = [span for span in result.offset_map if span.is_synthetic]
    assert len(synthetic) == int(expected is not None)
    if synthetic:
        assert synthetic[0].source_start is synthetic[0].source_end is None
        assert not synthetic[0].is_separator and synthetic[0].node_path.endswith("/a[1]")


@pytest.mark.parametrize(
    "base_href,context,expected",
    [
        (
            "https://catalogue.example.org/calls/",
            "https://final.example.org/page",
            "https://catalogue.example.org/calls/apply",
        ),
        (
            "../calls/",
            "https://final.example.org/pages/index",
            "https://final.example.org/calls/apply",
        ),
        ("", "https://final.example.org/pages/index", "https://final.example.org/pages/apply"),
        (
            "#terms",
            "https://final.example.org/pages/index",
            "https://final.example.org/pages/apply",
        ),
        ("javascript:bad", "https://final.example.org/page", None),
        (
            "https://catalogue.example.org/calls/",
            "file:///private/page.html",
            "https://catalogue.example.org/calls/apply",
        ),
        ("https://catalogue.example.org/calls/", None, None),
    ],
)
def test_html_base_policy(base_href: str, context: str | None, expected: str | None) -> None:
    markup = f'<html><head><base href="{base_href}"></head><body><a href="apply">Apply now</a></body></html>'
    result = clean_html(markup, base_url=context)
    assert result.text == (f"Apply now ({expected})" if expected else "Apply now")


def test_first_base_href_only_and_absolute_anchor_is_not_rebased() -> None:
    html = f'<head><base href="https://one.example.org/"><base href="https://two.example.org/"></head><main><a href="apply">One</a><a href="{URL}">Two</a></main>'
    result = clean_html(html, base_url="https://final.example.org/")
    assert result.text == f"One (https://one.example.org/apply)Two ({URL})"


@pytest.mark.parametrize(
    "href",
    [
        "",
        " ",
        "#section",
        "javascript:alert(1)",
        "JaVaScRiPt:bad",
        "mailto:fictional@example.org",
        "tel:12345",
        "data:text/plain,fiction",
        "ftp://example.org/apply",
    ],
)
def test_skipped_link_references(href: str) -> None:
    result = clean_html(f'<a href="{href}">Original words</a>', base_url="https://example.org/page")
    assert result.text == "Original words" and not any(s.is_synthetic for s in result.offset_map)


@pytest.mark.parametrize("label", [URL, "example.org/apply", "//example.org/apply", f"  {URL}  "])
def test_already_visible_target_is_not_duplicated(label: str) -> None:
    result = clean_html(f'<a href="{URL}">{label}</a>')
    assert result.text == label.strip() and not any(s.is_synthetic for s in result.offset_map)


def test_nested_inline_text_spacing_and_href_encoding() -> None:
    target = "https://Example.org/%2fApply?q=A%2FB&keep=Yes#Section"
    result = clean_html(
        '<p>Before <a href="https://Example.org/%2fApply?q=A%2FB&amp;keep=Yes#Section"> Apply <b>now</b> </a> after.</p>'
    )
    assert result.text == f"Before Apply now ({target}) after."
    assert (
        clean_html(f'<p><a href="{URL}"><b>Apply</b><i>now</i></a>end</p>').text
        == f"Applynow ({URL})end"
    )


@pytest.mark.parametrize(
    "markup",
    [
        f'<a href="{URL}"></a>',
        f'<a href="{URL}"><span hidden>Excluded label</span></a>',
        f'<div style="display:none"><a href="{URL}">Hidden</a></div>',
        f'<!-- <a href="{URL}">Commented link</a> -->',
        f'<nav><a href="{URL}">Menu link</a></nav>',
        f'<footer><a href="{URL}">Footer link</a></footer>',
    ],
)
def test_excluded_or_empty_links_stay_excluded(markup: str) -> None:
    result = clean_html(
        f"<main><p>Fictional content.</p>{markup}</main>", base_url="https://example.org/"
    )
    assert result.text == "Fictional content." and URL not in result.text
    assert not any(s.is_synthetic for s in result.offset_map)


def assert_map_round_trip(markup: str) -> None:
    result = clean_html(markup, base_url="https://example.org/page")
    tree = etree.HTML(markup)
    cursor = 0
    for span in result.offset_map:
        assert span.start == cursor and span.end > span.start
        cursor = span.end
        node = tree.xpath(span.node_path)[0]
        if span.is_synthetic:
            assert span.source_start is span.source_end is None and node.tag == "a"
            assert node.get("href") is not None and not span.is_separator
        elif span.is_separator:
            assert span.source_start is span.source_end is None
        else:
            assert span.source_start is not None and span.source_end is not None
            assert (
                re.sub(r"\s+", " ", str(node)[span.source_start : span.source_end])
                == result.text[span.start : span.end]
            )
    assert cursor == len(result.text)
    doc = segment(result, max_chars=50)
    for passage in doc.passages:
        assert passage.text == doc.text[passage.start : passage.end]
        for ref in passage.source_refs:
            if isinstance(ref, SourceSpan) and ref.is_synthetic:
                assert ref.source_start is ref.source_end is None and not ref.is_separator


def test_synthetic_map_and_cross_anchor_quote_round_trip() -> None:
    markup = f'<main><p>Start <a href="{URL}">Apply <strong>now</strong></a> for this fictional award.</p></main>'
    assert_map_round_trip(markup)
    doc = segment(clean_html(markup), max_chars=50)
    quote = f"Apply now ({URL})"
    start = doc.text.index(quote)
    refs = source_refs_for_range(doc, start, start + len(quote))
    assert any(isinstance(s, SourceSpan) and s.is_synthetic for s in refs)
    assert all(start <= s.start < s.end <= start + len(quote) for s in refs)


def test_many_table_links_keep_separators_and_source_flags() -> None:
    rows = "".join(
        "<tr>"
        + "".join(
            f'<td><a href="https://example.org/apply/{i}-{j}">Apply {i}-{j}</a></td>'
            for j in range(4)
        )
        + "</tr>"
        for i in range(3)
    )
    markup = f"<main><table>{rows}</table></main>"
    assert_map_round_trip(markup)
    cleaned = clean_html(markup)
    assert len(cleaned.text.splitlines()) == 3 and cleaned.text.count(" | ") == 9
    assert sum(s.is_synthetic for s in cleaned.offset_map) == 12
    doc = segment(cleaned, max_chars=80)
    for i in range(3):
        for j in range(4):
            target = f"https://example.org/apply/{i}-{j}"
            assert sum(target in p.text for p in doc.passages) == 1


def test_link_metadata_does_not_change_fragment_main_selection() -> None:
    markup = f'<main><a href="https://example.org/{"x" * 700}">Short</a></main><article><p>{"Fictional context. " * 80}</p></article>'
    assert clean_html(markup).root_used == "body"


@pytest.mark.parametrize("offsets", [(0, None), (None, 1), (0, 1)])
def test_synthetic_span_cannot_claim_dom_text_coordinates(
    offsets: tuple[int | None, int | None],
) -> None:
    with pytest.raises(ValueError, match="synthetic spans"):
        SourceSpan(0, 1, "/html[1]/body[1]/a[1]", *offsets, is_synthetic=True)


def test_full_pipeline_link_only_url_and_anchor_provenance() -> None:
    data = f'<main><h1>{TITLE}</h1><p><a href="../apply">Apply now</a></p></main>'.encode()
    target = "https://final.example.org/apply"
    quote = f"Apply now ({target})"

    def scripted(req: StructuredRequest[Any]) -> str:
        output = payload(req)
        if req.prompt_version == "identity-v1":
            pid = next(pid for pid, text in req.untrusted_passages if quote in text)
            output["application_link"] = field(target, quote, pid)
        return json.dumps(output)

    result = run_pipeline(
        replace(fetch(data), final_url="https://final.example.org/calls/index"),
        FakeClient(responses=[scripted] * 5),
    )
    assert result.status == "ok" and result.record and result.extraction and result.verification
    assert not result.extraction.rejected_items
    assert result.record.fields.application_link.verification == "verified"
    assert result.record.fields.application_link.value == target
    item = next(i for i in result.verification.items if i.owner_path == "fields.application_link")
    assert item.matched is not None and item.locator and item.locator.endswith("/a[1]")
    assert any(isinstance(ref, SourceSpan) and ref.is_synthetic for ref in item.source_refs)
    assert (
        result.record.fields.application_link.evidence[0].locator is None
    )  # Never rewrite citations.
    assert result.versions["cleaner"] == CLEANER_VERSION == "2"


def test_quote_across_passages_retains_anchor_locator_and_exact_offsets() -> None:
    data = f'<main><h1>{TITLE}</h1><p>Introductory fictional words before this anchor <a href="{URL}">Apply now</a> with more text after it.</p></main>'.encode()
    doc = segment(clean_html(data), max_chars=50)
    quote = f"Apply now ({URL})"
    start = doc.text.index(quote)
    cited = next(p.id for p in doc.passages if p.start <= start < p.end)

    def scripted(req: StructuredRequest[Any]) -> str:
        output = payload(req)
        if req.prompt_version == "identity-v1":
            output["application_link"] = field(URL, quote, cited)
        return json.dumps(output)

    result = run_pipeline(fetch(data), FakeClient(responses=[scripted] * 5), max_chars=50)
    assert result.verification and result.record
    item = next(i for i in result.verification.items if i.owner_path == "fields.application_link")
    assert item.matched == (start, start + len(quote))
    assert doc.text[slice(*item.matched)] == quote
    assert item.locator and item.locator.endswith("/a[1]")
    assert result.record.fields.application_link.verification == "verified"


def test_snapshot_uses_final_url_and_bumped_cleaner(tmp_path: Path) -> None:
    data = b'<main><a href="apply">Apply now</a></main>'
    fetched = replace(fetch(data), final_url="https://final.example.org/calls/")
    new = snapshot_page(fetched, "fictional", snapshots_dir=tmp_path)
    assert (
        tmp_path / "fictional.txt"
    ).read_text() == "Apply now (https://final.example.org/calls/apply)"
    old_text = "Apply now"
    old = new.model_copy(
        update={
            "cleaner_version": "1",
            "cleaned_text_sha256": hashlib.sha256(old_text.encode()).hexdigest(),
        }
    )
    drift = classify_drift(old, new)
    assert old.content_sha256 == new.content_sha256
    assert drift.classification == "tool_version_changed" and drift.cleaned_text_changed


def test_hidden_injected_link_is_still_rejected_by_unchanged_guard() -> None:
    data = f'<main><h1>{TITLE}</h1><a style="display:none" href="{URL}">Apply now</a><!-- <a href="{URL}">Commented link</a> --></main>'.encode()

    def scripted(req: StructuredRequest[Any]) -> str:
        assert all(URL not in text for _, text in req.untrusted_passages)
        output = payload(req)
        if req.prompt_version == "identity-v1":
            output["application_link"] = field(URL, TITLE, req.untrusted_passages[0][0])
        return json.dumps(output)

    result = run_pipeline(fetch(data), FakeClient(responses=[scripted] * 5))
    assert result.extraction and result.record
    assert result.extraction.rejected_items[0].reason == "URL_NOT_ON_PAGE"
    assert result.record.fields.application_link.value is None


def test_navigation_wrapper_keeps_only_main_link_targets() -> None:
    markup = f'<nav><a href="https://menu.example.org/">Menu</a><main><a href="{URL}">Apply now</a></main></nav>'
    result = clean_html(markup)
    assert result.text == f"Apply now ({URL})" and "menu.example.org" not in result.text
