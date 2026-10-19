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


@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_aspnet_wrapping_form_preserves_eligibility(as_bytes: bool) -> None:
    markup = """<html><body><form id='aspnetForm' runat='server'>
    <header>Page banner</header><article><h1>Eligibility</h1>
    <p>Applicants must hold a bachelor's degree.</p></article>
    <input type='hidden' name='__VIEWSTATE' value='fictional-state'>
    <button>Submit</button></form></body></html>"""
    result = clean_html(markup.encode() if as_bytes else markup)
    assert result.text == "Eligibility\nApplicants must hold a bachelor's degree."
    assert result.root_used == "body"
    assert_complete_map(result)
    assert all("/form[1]/article[1]/" in span.node_path for span in result.offset_map)


def test_form_controls_removed_without_discarding_content() -> None:
    markup = """<form runat='server'><h1>Requirements</h1><p>English proficiency is required.</p>
    <input value='ignore'><select><option>Choose an option</option></select>
    <textarea>Draft answer</textarea><button>Apply</button>
    <div role='combobox'>Widget options</div><span role='checkbox'>Unchecked</span>
    <div role='textbox' aria-label>Unlabeled editor</div>
    <p>Deadline: 1 May.</p></form>"""
    result = clean_html(markup)
    assert result.text == "Requirements\nEnglish proficiency is required.\nDeadline: 1 May."
    assert_complete_map(result)


@pytest.mark.parametrize(
    "marker",
    [
        "role='search'",
        "id='searchForm'",
        "class='site-login-panel'",
        "aria-label='Sign in'",
        "action='/account/log-in'",
    ],
)
def test_marked_search_login_forms_removed(marker: str) -> None:
    result = clean_html(
        f"<form {marker}><h2>Account tools</h2><p>UI instructions</p></form>"
        "<article><p>Applicants from abroad are eligible.</p></article>"
    )
    assert result.text == "Applicants from abroad are eligible."
    assert_complete_map(result)


def test_content_form_prose_mentioning_search_is_retained() -> None:
    result = clean_html(
        "<form id='application-form'><p>Search the published programme requirements.</p>"
        "<p>Research applicants are eligible.</p></form>"
    )
    assert (
        result.text
        == "Search the published programme requirements.\nResearch applicants are eligible."
    )


@pytest.mark.parametrize("container", ["main", "article", "section"])
@pytest.mark.parametrize("header_role", ["", "role='banner'"])
def test_content_header_heading_is_kept(container: str, header_role: str) -> None:
    result = clean_html(
        f"<{container}><header {header_role}><h1>Fictional award</h1></header>"
        f"<p>Full funding is available.</p></{container}>"
    )
    assert result.text == "Fictional award\nFull funding is available."
    assert result.root_used == ("main" if container == "main" else "body")
    assert any("/header[1]/h1[1]/text()[1]" in span.node_path for span in result.offset_map)
    assert_complete_map(result)


def test_page_level_header_banner_and_navigation_are_dropped() -> None:
    result = clean_html(
        "<header role='banner'><h1>Site name</h1><nav>Links</nav><p>Promotional text</p></header>"
        "<article><header><h1>Eligibility</h1></header><p>A degree is required.</p></article>"
    )
    assert result.text == "Eligibility\nA degree is required."
    assert result.root_used == "body"


@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_document_title_is_separate_from_offset_mapped_text(as_bytes: bool) -> None:
    markup = """<html><head><meta charset='utf-8'><title>  Award &amp; eligibility
       — 2027 </title></head><body><main><p>Applicants need a degree.</p></main></body></html>"""
    payload = markup.encode("utf-8") if as_bytes else markup
    result = clean_html(payload)
    assert result.title == "Award & eligibility — 2027"
    assert result.text == "Applicants need a degree."
    assert result.root_used == "main"
    assert all("/title[" not in span.node_path for span in result.offset_map)
    assert clean_html(payload) == result
    assert_complete_map(result)


@pytest.mark.parametrize("head", ["", "<title> \n\t </title>"])
def test_absent_or_blank_title_is_none(head: str) -> None:
    result = clean_html(f"<html><head>{head}</head><body><p>Requirements.</p></body></html>")
    assert result.title is None
    assert result.root_used == "body"
    assert result.text == "Requirements."


@pytest.mark.parametrize(
    ("main_length", "outside_length", "expected_root"),
    [
        (499, 1200, "body"),
        (500, 1500, "main"),
        (30, 69, "main"),  # Exactly 30% of the normalized body length (100).
        (29, 70, "body"),
        (20, 30, "main"),
        (5, 100, "body"),
        (0, 30, "body"),
    ],
)
def test_fragment_main_fallback_thresholds(
    main_length: int, outside_length: int, expected_root: str
) -> None:
    main_text = "M" * main_length
    outside_text = "B" * outside_length
    markup = f"<html><body><main><p>{main_text}</p></main><p>{outside_text}</p></body></html>"
    result = clean_html(markup)
    assert result.root_used == expected_root
    assert result.text == (
        "\n".join(part for part in [main_text, outside_text] if part)
        if expected_root == "body"
        else main_text
    )
    assert clean_html(markup) == result
    assert_complete_map(result)
    if expected_root == "body":
        original = lxml_html.document_fromstring(markup).getroottree()
        outside_spans = [
            span
            for span in result.offset_map
            if span.node_path == "/html[1]/body[1]/p[1]/text()[1]"
        ]
        assert outside_spans
        for span in outside_spans:
            source = str(original.xpath(span.node_path)[0])
            assert result.text[span.start : span.end] == source[span.source_start : span.source_end]


def test_large_navigation_noise_does_not_force_body_fallback() -> None:
    markup = f"<body><nav>{'Navigation ' * 1000}</nav><main><h1>Eligibility</h1></main></body>"
    result = clean_html(markup)
    assert result.text == "Eligibility"
    assert result.root_used == "main"


def test_multiple_main_roots_use_combined_length_for_fallback() -> None:
    result = clean_html(f"<main>{'A' * 200}</main><main>{'B' * 200}</main><p>{'C' * 600}</p>")
    assert result.root_used == "main"
    assert result.text == "A" * 200 + "\n" + "B" * 200
    assert_complete_map(result)


@pytest.mark.parametrize("wrapper", ["nav", "div role='navigation'"])
@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_navigation_wrapper_preserves_main_without_menu_noise(wrapper: str, as_bytes: bool) -> None:
    tag = wrapper.split()[0]
    markup = (
        f"<body><{wrapper} class='synthetic-shell'><a>Menu noise</a>"
        "<div class='synthetic-container'><main class='synthetic-main'>"
        "<h1>Fictional notice</h1><p>Original content stays intact.</p>"
        f"</main><a>More menu noise</a></div></{tag}></body>"
    )
    result = clean_html(markup.encode() if as_bytes else markup)
    assert result.text == "Fictional notice\nOriginal content stays intact."
    assert result.root_used == "main"
    assert clean_html(markup) == result
    assert_complete_map(result)
    assert any("/div[1]/main[1]/p[1]/text()[1]" in s.node_path for s in result.offset_map)


def test_navigation_wrapper_does_not_leak_menu_during_body_fallback() -> None:
    result = clean_html(
        "<body><nav><a>Menu noise</a><div><main><p>Brief notice.</p></main></div>"
        f"<p>More menu noise</p></nav><article><p>{'Body content. ' * 40}</p></article></body>"
    )
    assert result.root_used == "body"
    assert result.text.startswith("Brief notice.\nBody content.")
    assert "Menu noise" not in result.text
    assert "More menu noise" not in result.text
    assert_complete_map(result)


@pytest.mark.parametrize("hidden", ["hidden", "aria-hidden='true'"])
def test_navigation_wrapper_still_respects_hidden_ancestors(hidden: str) -> None:
    result = clean_html(
        f"<nav><div {hidden}><main><p>Invisible content</p></main></div></nav>"
        "<article><p>Visible notice.</p></article>"
    )
    assert result.text == "Visible notice."
    assert result.root_used == "body"


@pytest.mark.parametrize(
    ("input_bytes", "text_length", "expected"),
    [(5_000, 199, False), (5_001, 199, True), (5_001, 200, False), (5_001, 0, True)],
)
@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_suspiciously_empty_thresholds(
    input_bytes: int, text_length: int, expected: bool, as_bytes: bool
) -> None:
    markup = f"<body><p>{'x' * text_length}</p><!----></body>"
    markup = markup.replace("<!---->", "<!--" + " " * (input_bytes - len(markup)) + "-->")
    assert len(markup.encode()) == input_bytes
    result = clean_html(markup.encode() if as_bytes else markup)
    assert result.text == "x" * text_length
    assert result.suspiciously_empty is expected
    assert_complete_map(result)


@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_suspiciously_empty_string_size_is_measured_in_utf8_bytes(as_bytes: bool) -> None:
    markup = "<body><p>Brief.</p><!--" + "界" * 2_000 + "--></body>"
    assert len(markup) < 5_000 < len(markup.encode())
    result = clean_html(markup.encode() if as_bytes else markup)
    assert result.text == "Brief."
    assert result.suspiciously_empty
