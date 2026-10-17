from __future__ import annotations

import re

import pytest
from lxml import html as lxml_html

from scholarscope.cleaner import CleanedHTML, clean_html

# All fixtures are fictional, hand-authored HTML; none are downloaded pages.
CASES = [
    pytest.param(
        """<html><head><title>Site title</title><style>p { color: red }</style></head>
        <body><header>Site header</header><nav>Menu</nav><main><h1>Fictional grant</h1>
        <p>Tuition is covered.</p><nav>Local menu</nav><footer>Local footer</footer>
        <script>ignore_this()</script><style>.x { display: none }</style>
        <form>Search<input value='noise'><button>Go</button></form></main>
        <footer>Site footer</footer></body></html>""",
        "Fictional grant\nTuition is covered.",
        id="navigation-header-footer-scripts-styles-forms",
    ),
    pytest.param(
        """<main><h2>Funding</h2><table><caption>Annual amounts</caption>
        <thead><tr><th>Type</th><th>EUR</th></tr></thead><tbody>
        <tr><td>Tuition</td><td>12,000</td></tr>
        <tr><td><p>Stipend</p><p>per year</p></td><td><b>8,000</b></td></tr>
        </tbody></table></main>""",
        "Funding\nAnnual amounts\nType | EUR\nTuition | 12,000\nStipend per year | 8,000",
        id="table-rows-cells-and-inline-cell-blocks",
    ),
    pytest.param(
        """<main><h2>Eligibility</h2><ol><li>Degree<ul><li>Bachelor's</li>
        <li>Master's</li></ul></li><li>Language<ul><li>English</li></ul></li></ol></main>""",
        "Eligibility\nDegree\nBachelor's\nMaster's\nLanguage\nEnglish",
        id="nested-lists",
    ),
    pytest.param(
        """<main><p>Visible</p><p hidden>Hidden attribute</p>
        <div aria-hidden='TRUE'><p>Hidden descendant</p></div>
        <p style='DISPLAY: none !important'>Display hidden</p>
        <p style='color: red; visibility: hidden'>Visibility hidden</p>
        <p style='visibility: collapse'>Collapsed</p>
        <p style='content-visibility: hidden'>Content hidden</p><p>Still visible</p></main>""",
        "Visible\nStill visible",
        id="hidden-attributes-and-inline-css",
    ),
    pytest.param(
        "<main><p>Research &amp; development &lt; 5</p><p>Fees:&nbsp;&#8364;1,000 &copy;</p></main>",
        "Research & development < 5\nFees: €1,000 ©",
        id="entities-and-nonbreaking-space",
    ),
    pytest.param(
        """<html><body><nav>Noise</nav><article><h2>Fictional award</h2>
        <p>Deadline: 1 May.</p></article><div>Contact the foundation.</div>
        <footer>Noise</footer></body></html>""",
        "Fictional award\nDeadline: 1 May.\nContact the foundation.",
        id="body-fallback-without-main",
    ),
    pytest.param("", "", id="empty-input"),
    pytest.param(
        "<main><h2>Eligibility</h2><p>Degree: <b>Master's<p>Deadline: May 5",
        "Eligibility\nDegree: Master's\nDeadline: May 5",
        id="malformed-html",
    ),
    pytest.param(
        "<main><pre>2027 CALL\r\n  Degree     MSc\n\tDeadline: 1 May\n</pre></main>",
        "2027 CALL\nDegree MSc\nDeadline: 1 May",
        id="pdf-like-preformatted-text",
    ),
    pytest.param(
        """<html><head><meta charset='utf-8'></head><body><main><h2>申请条件</h2>
        <p>硕士学位</p><p>التمويل متاح</p><p>Bourse d’études — Universität</p>
        </main></body></html>""",
        "申请条件\n硕士学位\nالتمويل متاح\nBourse d’études — Universität",
        id="non-english-unchanged",
    ),
    pytest.param(
        "<main><p><span>20</span><b>27</b>: <em>fully</em> funded, <a>apply</a>!</p></main>",
        "2027: fully funded, apply!",
        id="inline-spacing-and-punctuation",
    ),
    pytest.param(
        """<!doctype html><html><body><!-- hidden comment --><section role='main'>
        <h2>Requirements</h2><p>One<!-- do not join as text --> application.</p>
        </section></body></html>""",
        "Requirements\nOne application.",
        id="role-main-comments-and-doctype",
    ),
    pytest.param(
        """<main><div class='js-cookie-banner'>Accept cookies</div>
        <div id='cookieConsent'>Preferences</div><div id='onetrust-consent-sdk'>Cookies</div>
        <div role='dialog' aria-label='Cookie preferences'>Cookie settings</div>
        <p>Cookie research is eligible.</p></main>""",
        "Cookie research is eligible.",
        id="cookie-banners-without-removing-topic-text",
    ),
    pytest.param(
        "<p>Outside</p><main><h1>Inside</h1><p>Details.</p></main><p>Outside again</p>",
        "Inside\nDetails.",
        id="main-preferred-over-page-surroundings",
    ),
    pytest.param(
        "<main hidden>Invisible main</main><article><h2>Visible fallback</h2><p>Read this.</p></article>",
        "Visible fallback\nRead this.",
        id="hidden-main-does-not-suppress-body-fallback",
    ),
    pytest.param(
        "<main><h1>First</h1><main><p>Nested once.</p></main></main><main><h2>Second</h2></main>",
        "First\nNested once.\nSecond",
        id="multiple-and-nested-main-containers",
    ),
    pytest.param(
        "<main><p>First<br>Second</p><h2>Next</h2><p>Third</p></main>",
        "First\nSecond\nNext\nThird",
        id="line-breaks-and-headings",
    ),
    pytest.param(
        "<main><table><tr><td></td><td>B</td></tr><tr><td>A</td><td></td></tr></table></main>",
        " | B\nA | ",
        id="empty-table-cells-retain-column-separators",
    ),
]


def assert_complete_map(result: CleanedHTML) -> None:
    cursor = 0
    for span in result.offset_map:
        assert span.start == cursor
        assert span.start < span.end <= len(result.text)
        assert span.node_path
        assert (span.source_start is None) == (span.source_end is None)
        cursor = span.end
    assert cursor == len(result.text)


@pytest.mark.parametrize(("markup", "expected"), CASES)
@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_synthetic_pages_are_cleaned_deterministically(
    markup: str, expected: str, as_bytes: bool
) -> None:
    payload = markup.encode("utf-8") if as_bytes else markup
    result = clean_html(payload)
    assert result.text == expected
    assert clean_html(payload) == result
    assert_complete_map(result)


def test_offset_round_trip_to_original_dom_nodes() -> None:
    markup = """<html><body><main><p hidden>Noise</p><h2>Funding</h2>
    <p>Fees: <strong>EUR&nbsp;10,000</strong> per year.</p>
    <table><tr><th>Type</th><th>Value</th></tr><tr><td>Award</td><td>Full</td></tr></table>
    <pre>Degree:\nMSc</pre></main></body></html>"""
    result = clean_html(markup)
    original = lxml_html.document_fromstring(markup).getroottree()
    assert_complete_map(result)
    for span in result.offset_map:
        nodes = original.xpath(span.node_path)
        assert len(nodes) == 1
        output_slice = result.text[span.start : span.end]
        if span.is_separator:
            assert output_slice in {"\n", " ", " | "}
            assert span.source_end is None
        else:
            assert span.source_start is not None and span.source_end is not None
            node_text = str(nodes[0])
            source_slice = node_text[span.source_start : span.source_end]
            assert (
                re.sub(r"\s+", " ", source_slice).strip()
                == re.sub(r"\s+", " ", output_slice).strip()
            )
            assert re.search(r"/text\(\)\[\d+\]$", span.node_path)

    # A passage spanning inline markup still identifies the original source nodes.
    passage_start = result.text.index("EUR")
    passage_end = result.text.index("per year.") + len("per year.")
    passage_sources = [
        span
        for span in result.offset_map
        if span.start < passage_end and span.end > passage_start and not span.is_separator
    ]
    assert any("/strong[1]/text()[1]" in span.node_path for span in passage_sources)
    assert any("/p[2]/text()[2]" in span.node_path for span in passage_sources)
    assert all("/p[1]/" not in span.node_path for span in passage_sources)


def test_offsets_distinguish_repeated_text_and_original_sibling_positions() -> None:
    result = clean_html("<main><p hidden>Duplicate</p><p>Duplicate</p><p>Duplicate</p></main>")
    assert result.text == "Duplicate\nDuplicate"
    text_spans = [span for span in result.offset_map if not span.is_separator]
    assert len(text_spans) == 2
    assert text_spans[0].node_path.endswith("/p[2]/text()[1]")
    assert text_spans[1].node_path.endswith("/p[3]/text()[1]")
    assert text_spans[0].start == 0
    assert text_spans[1].start == len("Duplicate\n")


def test_declared_encoding_in_html_bytes() -> None:
    markup = (
        "<html><head><meta charset='windows-1252'></head><body><p>École: €500</p></body></html>"
    )
    result = clean_html(markup.encode("cp1252"))
    assert result.text == "École: €500"
    assert_complete_map(result)


def test_noise_only_page_has_no_text_or_offsets() -> None:
    result = clean_html("<nav>Navigation</nav><form>Search</form><script>noise()</script>")
    assert result == CleanedHTML(text="", offset_map=())
