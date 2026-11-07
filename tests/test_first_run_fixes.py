"""First-run regressions with fictional bytes and scripted/mocked providers only."""

from __future__ import annotations

import importlib.util
import json
import logging
import socket
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from test_extractor import content, fetch, field, payload, scripted
from test_extractor import source as source_info
from test_llm import client_for, request

from scholarscope.cleaner import clean_html
from scholarscope.eval.loader import GoldLabel
from scholarscope.eval.metrics import ProgramEvaluation
from scholarscope.eval.report import build_report, write_report
from scholarscope.extraction import PROMPT_VERSIONS
from scholarscope.extraction.wire import GROUP_MODELS
from scholarscope.llm.base import StructuredRequest, StructuredResponse, Usage
from scholarscope.llm.cache import FileCache, cache_key
from scholarscope.llm.errors import FailureCategory, FailureDetail
from scholarscope.llm.fake import FakeClient
from scholarscope.llm.gemini import GeminiClient
from scholarscope.pipeline import run_pipeline
from scholarscope.segmenter import segment

spec = importlib.util.spec_from_file_location(
    "extract_snapshot", Path(__file__).resolve().parents[1] / "scripts/extract_snapshot.py"
)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("live sockets forbidden in first-run regression tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "fake-v1")


@pytest.mark.parametrize(
    "status,message,category",
    [
        (429, "Capacity temporarily exhausted.", "rate_limited"),
        (500, "Temporary processing failure.", "server_error"),
        (400, "Malformed parameter.", "bad_request"),
        (400, "Invalid response JSON schema.", "schema_rejected"),
        (400, "Response schema has too many states; reduce complexity.", "schema_rejected"),
        (200, "Response schema is too complex.", "schema_rejected"),
        (403, None, "bad_request"),
    ],
)
def test_mocked_provider_failure_categories(
    status: int, message: str | None, category: FailureCategory
) -> None:
    body = {"error": {"message": message}} if message else {"error": {"code": status}}
    client, calls, _ = client_for("gemini", [httpx.Response(status, json=body)])
    response = client.generate_structured(request())
    assert response.status == "provider_error" and response.raw_text is None
    assert response.failure_detail == FailureDetail(category, status, message)
    assert len(calls) == (3 if status in {429, 500} else 1)


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "Invalid key gsk_FICTIONAL_SECRET_1234567890; token=fictional-token.",
            "Invalid key [redacted]; token=[redacted]",
        ),
        (
            "Request failed at https://example.invalid/api?key=fictional&mode=private",
            "Request failed at https://example.invalid/api",
        ),
        ("  Temporary\n\t processing failure.  ", "Temporary processing failure."),
        ("Unrelated diagnostic. " * 30, ("Unrelated diagnostic. " * 30)[:300]),
        ("Synthetic untrusted source text.", "[withheld: matched request text]"),
        ("x " * 170 + "Synthetic untrusted source text.", "[withheld: matched request text]"),
        ("Return a fictional integer value.", "[withheld: matched request text]"),
        ("Trusted rules repeated here exactly.", "[withheld: matched request text]"),
    ],
)
def test_message_sanitization(message: str, expected: str) -> None:
    client, _, _ = client_for("gemini", [httpx.Response(400, json={"error": {"message": message}})])
    response = client.generate_structured(request(system="Trusted rules repeated here exactly."))
    assert response.failure_detail and response.failure_detail.message == expected
    assert len(response.failure_detail.message) <= 300
    assert expected not in repr(response) + repr(response.failure_detail)


def test_known_key_and_non_message_fields_never_escape() -> None:
    key = "short-fictional-key"
    client, _, _ = client_for(
        "groq", [httpx.Response(400, json={"error": {"message": f"Invalid key {key}"}})]
    )
    client._key = SecretStr(key)
    response = client.generate_structured(request())
    assert response.failure_detail and response.failure_detail.message == "Invalid key [redacted]"
    assert key not in json.dumps(asdict(response), default=str)
    for body in ({"message": "Do not use root messages"}, {"error": "Not error.message"}):
        client, _, _ = client_for("gemini", [httpx.Response(400, json=body)])
        response = client.generate_structured(request())
        assert response.failure_detail and response.failure_detail.message is None
    client, _, _ = client_for("gemini", [httpx.Response(400, text="Never use raw text")])
    response = client.generate_structured(request())
    assert response.failure_detail and response.failure_detail.message is None


def test_provider_schema_error_code_without_message() -> None:
    client, calls, _ = client_for(
        "groq", [httpx.Response(400, json={"error": {"code": "invalid_json_schema"}})]
    )
    response = client.generate_structured(request())
    assert response.failure_detail == FailureDetail("schema_rejected", 400)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error_type,category", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "other")]
)
def test_transport_exception_text_is_discarded(error_type: Any, category: FailureCategory) -> None:
    client, _, _ = client_for("gemini", [error_type("PRIVATE_EXCEPTION_SENTINEL")])
    response = client.generate_structured(request())
    assert response.failure_detail == FailureDetail(category)
    assert "PRIVATE_EXCEPTION_SENTINEL" not in repr(response) + json.dumps(
        asdict(response), default=str
    )


@pytest.mark.parametrize(
    "category",
    ["rate_limited", "server_error", "bad_request", "timeout", "schema_rejected", "other"],
)
def test_fake_failure_details_flow_to_every_failed_group(category: FailureCategory) -> None:
    class FailureClient(FakeClient):
        def generate_structured(self, req: StructuredRequest[Any]) -> StructuredResponse[Any]:
            return StructuredResponse(
                "provider_error",
                failure_detail=FailureDetail(category, 400, "Safe diagnostic."),
                usage=Usage(input_tokens=13, output_tokens=2),
            )

    result = run_pipeline(fetch(content("simple")), FailureClient())
    assert result.extraction and result.record
    extraction = result.extraction
    assert set(extraction.failed_groups) == set(GROUP_MODELS)
    assert extraction.failure_details == {
        group: FailureDetail(category, 400, "Safe diagnostic.") for group in GROUP_MODELS
    }
    assert all(extraction.group_status[group] == "failed" for group in GROUP_MODELS)
    assert all(value >= 0 for value in extraction.group_latency_seconds.values())
    assert set(extraction.group_latency_seconds) == set(GROUP_MODELS)
    assert extraction.group_usage == {
        g: Usage(input_tokens=13, output_tokens=2) for g in GROUP_MODELS
    }
    assert extraction.usage == Usage(input_tokens=65, output_tokens=10)
    assert result.record.notes == "\n".join(
        f"EXTRACTION_FAILED:{group}:provider_error" for group in GROUP_MODELS
    )
    assert "Safe diagnostic." not in result.record.model_dump_json()


def test_diagnostics_are_console_only_and_never_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    sentinel = "Ephemeral capacity diagnostic."
    key_like = "gsk_FICTIONAL_SECRET_1234567890"
    sanitized = sentinel + " key [redacted]"
    data = content("simple")
    snapshots = tmp_path / "private-snapshots"
    snapshots.mkdir()
    snapshot = snapshots / "fictional-award.html"
    snapshot.write_bytes(data)
    cache = FileCache(tmp_path / "cache")
    assert cache.put("fake", "unrelated-model", request(), '{"value": 1}', Usage())
    cache_before = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                400, json={"error": {"message": sentinel + " key " + key_like}}
            )
        )
    )
    client = GeminiClient(
        "fictional-model", api_key=SecretStr("fictional-key"), http_client=http, cache=cache
    )
    result = run_pipeline(fetch(data), client)
    assert result.extraction and result.record
    assert all(d.message == sanitized for d in result.extraction.failure_details.values())
    monkeypatch.setattr(cli, "build_client", lambda config: client)
    monkeypatch.setattr(
        "sys.argv",
        ["extract_snapshot", "--slug", "fictional-award", "--snapshots-dir", str(snapshots)],
    )
    assert cli.main() == 1
    printed = capsys.readouterr().out
    assert sentinel in printed
    assert key_like not in printed
    summary = json.loads(printed[json.JSONDecoder().raw_decode(printed)[1] :].strip())
    assert set(summary["failure_details"]) == set(summary["failed_groups"]) == set(GROUP_MODELS)
    assert all(d["message"] == sanitized for d in summary["failure_details"].values())
    assert sentinel not in caplog.text + repr(result) + result.record.model_dump_json()
    assert {p.name: p.read_bytes() for p in cache.directory.iterdir()} == cache_before
    assert list(snapshots.iterdir()) == [snapshot] and snapshot.read_bytes() == data
    label = GoldLabel("fictional-award", result.record, {})
    program = ProgramEvaluation(label, result, segment(clean_html(data)), "fictional", 0.0)
    report = build_report([program], [], date="2026-11-06", git_commit="fictional")
    out = tmp_path / "reports" / "fictional.json"
    write_report(report, [program], out)
    assert sentinel not in json.dumps(report)
    assert all(sentinel not in p.read_text(encoding="utf-8") for p in out.parent.iterdir())


def run_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    client: FakeClient,
    *args: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    (tmp_path / "fictional-award.html").write_bytes(
        content("simple") + b'<main><a href="/applications">Apply here</a></main>'
    )
    monkeypatch.setattr(cli, "build_client", lambda config: client)
    monkeypatch.setattr(
        "sys.argv",
        ["extract_snapshot", "--slug", "fictional-award", "--snapshots-dir", str(tmp_path), *args],
    )
    assert cli.main() == 0
    text = capsys.readouterr().out
    record, end = json.JSONDecoder().raw_decode(text)
    return record, json.loads(text[end:].strip())


@pytest.mark.parametrize("supplied", [False, True])
def test_source_url_resolves_retained_relative_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    supplied: bool,
) -> None:
    target = "https://example.invalid/applications"

    def respond(req: StructuredRequest[Any]) -> str:
        data = payload(req)
        if req.prompt_version.startswith("identity-"):
            pid = next(pid for pid, text in req.untrusted_passages if "Apply here" in text)
            data["application_link"] = field(target, "Apply here", pid)
        return json.dumps(data)

    client = FakeClient(responses=[respond] * 5)
    args = ("--source-url", "https://example.invalid/award") if supplied else ()
    record, summary = run_cli(tmp_path, monkeypatch, capsys, client, *args)
    sent = "\n".join(text for _, text in client.requests[0].untrusted_passages)
    assert (target in sent) is supplied
    assert summary["source_url_user_supplied"] is supplied
    assert record["fields"]["application_link"]["value"] == (target if supplied else None)
    if supplied:
        assert record["source"]["url"] == "https://example.invalid/award"
        assert record["fields"]["application_link"]["verification"] == "verified"
    else:
        assert record["source"]["url"].startswith("file:")
        assert summary["rejected_item_details"][0]["reason"] == "URL_NOT_ON_PAGE"
    assert summary["truncated"] is False and summary["passages_dropped"] == 0
    assert set(summary["group_status"]) == set(GROUP_MODELS)
    assert set(summary["group_latency_seconds"]) == set(GROUP_MODELS)
    assert summary["group_usage"] == {g: Usage().model_dump() for g in GROUP_MODELS}


@pytest.mark.parametrize(
    "requested_url,final_url,supplied_source_url,target",
    [
        (
            "https://example.invalid/requested/index.html",
            "https://example.invalid/redirected/index.html",
            "https://example.invalid/metadata/index.html",
            "https://example.invalid/redirected/apply",
        ),
        (
            "file:///private/fictional-award.html",
            None,
            "https://example.invalid/local/index.html",
            "https://example.invalid/local/apply",
        ),
        ("file:///private/fictional-award.html", None, None, None),
        (
            "https://example.invalid/requested/index.html",
            None,
            "https://example.invalid/metadata/index.html",
            "https://example.invalid/requested/apply",
        ),
        (
            "file:///private/fictional-award.html",
            None,
            "file:///metadata/fictional-award.html",
            None,
        ),
    ],
    ids=[
        "http-redirect",
        "file-with-http-source",
        "file-without-source",
        "http-request-url",
        "file-with-file-source",
    ],
)
def test_pipeline_cleaner_base_precedence(
    requested_url: str, final_url: str | None, supplied_source_url: str | None, target: str | None
) -> None:
    data = content("simple") + b'<main><a href="apply">Apply here</a></main>'
    fetched = replace(fetch(data), url=requested_url, final_url=final_url)
    supplied_source = (
        source_info(data).model_copy(update={"url": supplied_source_url})
        if supplied_source_url
        else None
    )

    def respond(req: StructuredRequest[Any]) -> str:
        answer = payload(req)
        if target and req.prompt_version.startswith("identity-"):
            pid = next(pid for pid, text in req.untrusted_passages if "Apply here" in text)
            answer["application_link"] = field(target, "Apply here", pid)
        return json.dumps(answer)

    client = FakeClient(responses=[respond] * 5)
    result = run_pipeline(fetched, client, source=supplied_source)
    assert result.status == "ok" and result.record and result.extraction
    sent = "\n".join(text for _, text in client.requests[0].untrusted_passages)
    if target:
        assert target in sent
        assert result.record.fields.application_link.value == target
        assert result.record.fields.application_link.verification == "verified"
    else:
        assert "https://" not in sent and "file://" not in sent
    assert "https://example.invalid/metadata/apply" not in sent
    assert not result.extraction.rejected_items


@pytest.mark.parametrize(
    "url",
    [
        "file:///private/file",
        "ftp://example.invalid/page",
        "https:///nohost",
        "https://user:secret@example.invalid/page",
        "https://example.invalid:bad",
    ],
)
def test_invalid_source_url_is_rejected_before_building_client(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["extract_snapshot", "--slug", "fictional-award", "--source-url", url]
    )
    monkeypatch.setattr(cli, "build_client", lambda config: pytest.fail("must not build client"))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("show", [False, True])
def test_rejected_raw_item_is_opt_in_and_empty_language_stays_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], show: bool
) -> None:
    sentinel = "PRIVATE_FICTIONAL_REJECTED_ITEM"

    def change(data: dict[str, Any], group: str) -> None:
        if group == "conditions":
            data["conditions"] = [
                {
                    "kind": "language",
                    "value": {"logic": "any", "options": []},
                    "required": True,
                    "applies_to": None,
                    "evidence": [],
                    "notes": sentinel,
                }
            ]

    client = FakeClient(responses=[scripted(change=change)] * 5)
    record, summary = run_cli(
        tmp_path, monkeypatch, capsys, client, *(("--show-rejected",) if show else ())
    )
    item = summary["rejected_item_details"][0]
    assert summary["rejected_items"] == 1 and item["group"] == "conditions" and item["index"] == 0
    assert "options" in item["reason"] and "at least 1" in item["reason"]
    assert ("raw_item" in item) is show
    assert (sentinel in json.dumps(summary)) is show
    assert record["conditions"] == []


@pytest.mark.parametrize("group", ["funding", "documents", "conditions"])
def test_v2_prompts_invalidate_cache_even_with_unchanged_task(group: str) -> None:
    req = request(prompt_version=f"{group}-v1")
    assert (
        PROMPT_VERSIONS[group]
        == {"funding": "funding-v3", "documents": "documents-v2", "conditions": "conditions-v3"}[
            group
        ]
    )
    assert cache_key("fake", "fictional", req) != cache_key(
        "fake", "fictional", replace(req, prompt_version=PROMPT_VERSIONS[group])
    )


def test_prompt_policy_and_fictional_domain_conversion() -> None:
    folder = Path(__file__).resolve().parents[1] / "scholarscope/extraction/prompts"
    funding = (folder / "funding.v2.txt").read_text(encoding="utf-8")
    documents = (folder / "documents.v2.txt").read_text(encoding="utf-8")
    conditions = (folder / "conditions.v2.txt").read_text(encoding="utf-8")
    assert '"Example Residence Permit Fee" -> other' in funding
    assert "Never map a cost to the nearest named category" in funding
    assert "page's own words" in documents and "Do not add documents" in documents
    assert "empty options list" in conditions and 'emit kind "other"' in conditions
    quote = "Fictional language proficiency is required."
    data = content("simple") + f"<p>{quote}</p>".encode()

    def change(answer: dict[str, Any], group: str) -> None:
        if group == "conditions":
            answer["conditions"] = [
                {
                    "kind": "other",
                    "value": quote,
                    "required": True,
                    "applies_to": None,
                    "notes": None,
                    "evidence": [{"quote": quote, "passage_id": None}],
                }
            ]

    result = run_pipeline(fetch(data), FakeClient(responses=[scripted(change=change)] * 5))
    assert result.record and result.extraction and not result.extraction.rejected_items
    assert (
        result.record.conditions[0].kind == "other" and result.record.conditions[0].value == quote
    )
