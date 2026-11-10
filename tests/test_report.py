"""Static report contracts; fictional data, sockets forbidden, no provider calls."""

from __future__ import annotations

import importlib.util
import re
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from report_fixtures import EXAMPLE_HTML, FIXED_NOW, SOURCE_URL, synthetic_result
from test_verifier import html_doc, record_for

from scholarscope.checklist import build_checklist
from scholarscope.extraction.convert import RejectedItem
from scholarscope.llm.base import BaseClient
from scholarscope.llm.cache import FileCache
from scholarscope.llm.config import LLMConfig, build_client
from scholarscope.llm.errors import FailureDetail
from scholarscope.pipeline import PipelineResult
from scholarscope.report import DISPLAY_LIMIT, SYNTHETIC_BANNER, render_report
from scholarscope.schema import Evidence
from scholarscope.verifier import QuoteOutcome, verify_record

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_report", ROOT / "scripts/render_report.py")
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("live sockets/provider sends forbidden in report tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr(BaseClient, "_send", fail)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "fake-v1")


def rendered(result: PipelineResult | None = None, *, supplied: bool = True) -> str:
    return render_report(
        result or synthetic_result(), now=FIXED_NOW, source_url_is_user_supplied=supplied
    )


def test_synthetic_sample_in_sync_deterministic_and_immutable() -> None:
    result = synthetic_result()
    before = repr(result), result.record.model_dump_json() if result.record else None
    output = rendered(result)
    assert output == rendered(synthetic_result())
    assert output.encode("utf-8") == (ROOT / "docs/examples/sample-report.html").read_bytes()
    assert before == (repr(result), result.record.model_dump_json() if result.record else None)
    soup = BeautifulSoup(output, "html.parser")
    assert SYNTHETIC_BANNER in soup.get_text()
    assert "quote found on page" in soup.get_text()
    assert "quote NOT found: excluded from checklist" in soup.get_text()
    assert "not_checked" in soup.get_text()
    assert "local read date" in soup.get_text()
    assert soup.footer and FIXED_NOW.isoformat() in soup.footer.get_text()
    assert not re.search(r"\b(?:precision|recall)\b|\d\s*%", output, re.IGNORECASE)
    assert "%" not in output


def test_failure_badges_rejections_and_provider_message_exclusion() -> None:
    result = synthetic_result()
    assert result.extraction
    extraction = replace(
        result.extraction,
        failed_groups=("identity", "funding"),
        group_status={**result.extraction.group_status, "funding": "failed"},
        failure_details={
            "funding": FailureDetail("schema_rejected", 400, "PRIVATE_PROVIDER_MESSAGE")
        },
        rejected_items=(
            RejectedItem("funding", 1, '<bad reason & "note">', {"private": "PRIVATE_RAW_ITEM"}),
        ),
        truncated=True,
        passages_dropped=3,
    )
    output = rendered(replace(result, extraction=extraction))
    text = BeautifulSoup(output, "html.parser").get_text()
    assert "NOT EXTRACTED (group failed)" in text and "schema_rejected" in text
    assert '<bad reason & "note">' in text
    assert "Input truncated: true" in text and "passages dropped: 3" in text
    assert "PRIVATE_PROVIDER_MESSAGE" not in output and "PRIVATE_RAW_ITEM" not in output
    assert "&lt;bad reason &amp; &quot;note&quot;&gt;" in output


def test_hostile_strings_are_inert_and_long_text_has_visible_truncation() -> None:
    result = synthetic_result()
    assert result.record
    hostile = '<script>alert("x")</script><img src="https://evil.invalid/pixel" onerror="bad()"> & < > " \' javascript:bad() \u202e'
    doc = html_doc(hostile + "Z" * (DISPLAY_LIMIT + 50))
    record = result.record.model_copy(deep=True)
    record.notes = hostile + "Z" * (DISPLAY_LIMIT + 50)
    record.fields.institution.value = hostile
    record.fields.application_link.value = "javascript:alert(1)"
    record.fields.application_link.linked_url = "https://evil.invalid/page"
    record.source.url = "javascript:alert(2)"
    output = rendered(replace(result, record=record, document=doc))
    soup = BeautifulSoup(output, "html.parser")
    assert not soup.find(["script", "img", "iframe", "link", "object", "svg", "form"])
    assert len(soup.find_all("style")) == 1
    for tag in soup.find_all(True):
        assert isinstance(tag, Tag)
        assert not any(name.lower().startswith("on") for name in tag.attrs)
        assert "src" not in tag.attrs and "style" not in tag.attrs
        if tag.has_attr("href"):
            assert str(tag["href"]).startswith("#")
    assert "<script>" not in output and "&lt;script&gt;" in output
    assert "&amp;" in output and "&quot;" in output and "&#x27;" in output
    assert "\u202e" not in output and "[U+202E]" in output
    assert "truncated" in soup.get_text() and "…" in soup.get_text()
    source_text = soup.select_one(".source-text")
    assert source_text and "Z" * (DISPLAY_LIMIT + 1) not in source_text.get_text()
    csp = soup.find("meta", attrs={"http-equiv": "Content-Security-Policy"})
    assert (
        isinstance(csp, Tag) and csp["content"] == "default-src 'none'; style-src 'unsafe-inline'"
    )


@pytest.mark.parametrize(
    "group,name",
    [
        ("identity", "program_name"),
        ("funding", "funding_coverage"),
        ("documents", "required_documents"),
    ],
)
def test_failed_group_placeholder_status_is_unknown_not_absent(group: str, name: str) -> None:
    result = synthetic_result()
    assert result.record and result.extraction
    record = result.record.model_copy(deep=True)
    item = getattr(record.fields, name)
    item.status, item.value, item.evidence, item.verification = "absent", None, [], "not_checked"
    before = record.model_dump_json()
    extraction = replace(result.extraction, failed_groups=(group,))
    soup = BeautifulSoup(
        rendered(replace(result, record=record, extraction=extraction)), "html.parser"
    )
    heading = soup.find("th", string=name)
    assert isinstance(heading, Tag)
    row = heading.find_parent("tr")
    assert isinstance(row, Tag)
    cells = row.find_all("td")
    assert cells[0].get_text() == "unknown (group failed)"
    assert "NOT EXTRACTED (group failed)" in cells[1].get_text()
    assert record.model_dump_json() == before  # Presentation only; placeholders remain unchanged.
    if group != "identity":
        healthy = soup.find("th", string="degree_levels")
        assert isinstance(healthy, Tag)
        healthy_row = healthy.find_parent("tr")
        assert isinstance(healthy_row, Tag)
        assert healthy_row.find_all("td")[0].get_text() == "absent"


def test_failed_deadline_set_status_is_unknown_not_absent() -> None:
    result = synthetic_result()
    assert result.record and result.extraction
    record = result.record.model_copy(deep=True)
    record.deadlines, record.deadlines_status = [], "absent"
    extraction = replace(result.extraction, failed_groups=("deadlines",))
    text = BeautifulSoup(
        rendered(replace(result, record=record, extraction=extraction)), "html.parser"
    ).get_text()
    assert "Set status: unknown (group failed)" in text
    assert "Set status: absent" not in text


@pytest.mark.parametrize("supplied", [True, False])
def test_only_explicit_user_source_url_is_an_external_href(supplied: bool) -> None:
    result = synthetic_result()
    output = rendered(result, supplied=supplied)
    soup = BeautifulSoup(output, "html.parser")
    external = [
        a for a in soup.find_all("a") if isinstance(a, Tag) and not str(a["href"]).startswith("#")
    ]
    assert [a["href"] for a in external] == ([SOURCE_URL] if supplied else [])
    if supplied:
        assert set(external[0]["rel"]) == {"noopener", "noreferrer", "nofollow"}
    assert "https://example.invalid/apply" in soup.get_text()
    assert not soup.find("a", href="https://example.invalid/apply")
    for anchor in soup.select('a[href^="#"]'):
        assert soup.find(id=anchor["href"][1:])


def test_checklist_matches_existing_builder_and_shows_warnings() -> None:
    result = synthetic_result()
    assert result.record
    zone = timezone(timedelta(hours=5))
    output = render_report(
        result, now=FIXED_NOW, reference_tz=zone, source_url_is_user_supplied=True
    )
    soup = BeautifulSoup(output, "html.parser")
    checklist = build_checklist(result.record, FIXED_NOW, reference_tz=zone)
    for item in checklist.items:
        rendered_item = soup.find("li", attrs={"data-checklist-id": item.id})
        assert rendered_item
        text = rendered_item.get_text()
        assert item.title in text and item.policy_id in text and item.policy_version in text
        assert (item.due_date.isoformat() if item.due_date else "not stated") in text
        assert all(str(warning) in text for warning in item.warnings)
        assert all(e.quote in text for e in item.evidence)
    assert "TIMEZONE_UNKNOWN" in soup.get_text()
    assert "Profile eligibility is not part of this report" in soup.get_text()


def test_ambiguous_and_unverified_claims_say_check_official_page() -> None:
    result = synthetic_result()
    assert result.record
    record = result.record.model_copy(deep=True)
    record.fields.required_documents.status = "ambiguous"
    record.fields.required_documents.value = None
    record.fields.required_documents.verification = "unverified"
    soup = BeautifulSoup(rendered(replace(result, record=record)), "html.parser")
    assert "check the official page" in soup.get_text()
    assert "Check official document requirements" in soup.get_text()
    assert "Prepare document: Example transcript" not in soup.get_text()


def test_spanning_quote_highlights_original_offsets_in_both_passages() -> None:
    doc = html_doc(
        "Example first paragraph has a closing phrase.",
        "Example second paragraph has the continuation.",
        max_chars=50,
    )
    assert len(doc.passages) >= 2
    a, b = doc.passages[:2]
    quote = doc.text[a.end - 20 : b.start + 20]
    record, report = verify_record(record_for([Evidence(quote=quote, passage_id=a.id)]), doc)
    assert report.items[0].outcome == QuoteOutcome.SPANS_PASSAGES
    result = replace(synthetic_result(), record=record, verification=report, document=doc)
    soup = BeautifulSoup(rendered(result), "html.parser")
    marks = soup.select("mark")
    assert len(marks) >= 2
    for mark in marks:
        start, end = int(str(mark["data-start"])), int(str(mark["data-end"]))
        assert mark.get_text() == doc.text[start:end]
        assert a.end - 20 <= start < end <= b.start + 20
    parents = [mark.find_parent("section") for mark in marks]
    assert all(isinstance(parent, Tag) for parent in parents)
    assert len({str(parent["id"]) for parent in parents if isinstance(parent, Tag)}) == 2


def test_synthetic_link_target_span_and_advisory_are_visible() -> None:
    result = synthetic_result()
    assert result.record and result.document
    url = "https://example.invalid/apply"
    passage = next(p for p in result.document.passages if url in p.text)
    record = result.record.model_copy(deep=True)
    record.fields.application_link.evidence = [Evidence(quote=url, passage_id=passage.id)]
    record, report = verify_record(record, result.document)
    soup = BeautifulSoup(
        rendered(replace(result, record=record, verification=report)), "html.parser"
    )
    assert "link target added by the cleaner" in soup.get_text()
    assert "flagged as suspicious (advisory)" in soup.get_text()
    assert soup.select("mark .synthetic")
    for marked in soup.select("mark .synthetic"):
        start, end = int(str(marked["data-start"])), int(str(marked["data-end"]))
        assert marked.get_text() == result.document.text[start:end]


def test_no_hidden_clock_or_naive_now_and_no_record_handled() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        render_report(
            synthetic_result(), now=datetime(2026, 11, 9), source_url_is_user_supplied=False
        )
    empty = PipelineResult("empty_text", None, None, None, {}, error="PRIVATE_FAILURE_BODY")
    text = rendered(empty)
    assert "PRIVATE_FAILURE_BODY" not in text
    assert "No source passages available" in text and "not extracted" in text


def cli_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> Path:
    snapshots = tmp_path / "private"
    snapshots.mkdir()
    (snapshots / "fictional-award.html").write_bytes(EXAMPLE_HTML)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["render_report", "--slug", "fictional-award", "--snapshots-dir", str(snapshots), *args],
    )
    return tmp_path / "eval/reports/fictional-award-report.html"


def test_cli_cache_only_overrides_env_and_cache_miss_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = cli_workspace(tmp_path, monkeypatch, "--source-url", SOURCE_URL)
    monkeypatch.setenv("LLM_CACHE_MODE", "off")
    configs = []
    clients = []

    def builder(config: LLMConfig) -> Any:
        configs.append(config)
        client = build_client(config, cache_dir=tmp_path / "cache")
        clients.append(client)
        monkeypatch.setattr(client, "_send", lambda *args: pytest.fail("cache-only provider call"))
        return client

    monkeypatch.setattr(cli, "build_client", builder)
    assert cli.main() == 1
    assert configs[0].cache_mode == "read_only"
    assert len(clients) == 1
    assert not (tmp_path / "cache").exists()
    output = target.read_text(encoding="utf-8")
    assert "NOT EXTRACTED (group failed)" in output
    assert "local read date" in output and "No source passages available" not in output
    assert "cache miss" not in output  # No free-form provider/error messages persisted.


def test_cli_live_option_uses_env_config_but_test_injects_only_fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from report_fixtures import scripted_response

    target = cli_workspace(tmp_path, monkeypatch, "--live", "--source-url", SOURCE_URL)
    configs = []

    def builder(config: LLMConfig) -> Any:
        configs.append(config)
        from scholarscope.llm.fake import FakeClient

        return FakeClient(responses=[scripted_response] * 5, cache=FileCache(mode="off"))

    monkeypatch.setattr(cli, "build_client", builder)
    assert cli.main() == 0 and target.is_file()
    assert configs[0].cache_mode == "read_write"


@pytest.mark.parametrize(
    "relative",
    [
        "eval/gold/out.html",
        "eval/snapshots/out.html",
        "docs/02-architecture.md",
        "docs/adr/out.html",
        "eval/reports/../gold/out.html",
        "outside.html",
    ],
)
def test_cli_refuses_protected_and_unapproved_output_before_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    cli_workspace(tmp_path, monkeypatch, "--out", str(tmp_path / relative))
    monkeypatch.setattr(cli, "build_client", lambda config: pytest.fail("must not build a client"))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert not (tmp_path / relative).exists()


def test_output_symlink_into_protected_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    protected = tmp_path / "eval/gold"
    protected.mkdir(parents=True)
    allowed = tmp_path / "eval/reports"
    allowed.mkdir()
    link = allowed / "alias.html"
    try:
        link.symlink_to(protected / "fictional.html")
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="gold or snapshots"):
        cli.output_path(link, "fictional")


def test_docs_example_requires_explicit_out_and_synthetic_flag_is_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    target = tmp_path / "docs/examples/sample-report.html"
    monkeypatch.setattr("sys.argv", ["render_report", "--synthetic-sample", "--out", str(target)])
    monkeypatch.setattr(cli, "synthetic_result", lambda: (synthetic_result(), FIXED_NOW))
    monkeypatch.setattr(
        cli, "build_client", lambda config: pytest.fail("no client factory for synthetic demo")
    )
    assert cli.main() == 0
    assert target.read_text(encoding="utf-8") == rendered()
    assert cli.output_path(None, "fictional").is_relative_to(tmp_path / "eval/reports")


@pytest.mark.parametrize("root", ["eval/reports", "docs/examples"])
def test_output_parent_symlink_cannot_redirect_to_unapproved_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    destination = tmp_path / "docs/adr"
    destination.mkdir(parents=True)
    link = tmp_path / root
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(destination, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="output must be HTML"):
        cli.output_path(link / "fictional.html", "fictional")
