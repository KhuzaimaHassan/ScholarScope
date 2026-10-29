"""Synthetic pages/metadata only; every writable path lives under tmp_path."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from test_fetcher import FakeServer
from test_pdf_text import make_text_pdf

from scholarscope.cleaner import CLEANER_VERSION, clean_html
from scholarscope.fetcher import Fetcher, FetchResult
from scholarscope.pdf_text import PDF_EXTRACTOR_VERSION
from scholarscope.segmenter import SEGMENTER_VERSION
from scholarscope.snapshots import (
    SnapshotManifest,
    SnapshotRecord,
    classify_drift,
    load_manifest,
    snapshot_page,
    write_manifest,
)

ROOT = Path(__file__).resolve().parent.parent
pytest_plugins = ["test_fetcher"]
spec = importlib.util.spec_from_file_location(
    "refetch_snapshots", ROOT / "scripts/refetch_snapshots.py"
)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
SENTINEL = "PRIVATE_PAGE_SENTINEL_do_not_publish"


def fetch_and_store(
    tmp_path: Path,
    fake_server: FakeServer,
    body: bytes,
    *,
    slug: str = "fictional-award",
    media: str = "text/html",
) -> SnapshotRecord:
    base, handler = fake_server
    handler.routes = {"/page": (200, body, {"Content-Type": media})}
    with Fetcher(tmp_path / "fetched", min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base}/page")
    return snapshot_page(result, slug, snapshots_dir=tmp_path / "copies")


def test_html_snapshot_names_hashes_and_metadata(tmp_path: Path, fake_server: FakeServer) -> None:
    body = f'<main data-nonce="123"><h1>Fictional award</h1><p>{SENTINEL}</p></main>'.encode()
    record = fetch_and_store(tmp_path, fake_server, body)
    assert (tmp_path / "copies/fictional-award.html").read_bytes() == body
    text = (tmp_path / "copies/fictional-award.txt").read_text(encoding="utf-8")
    assert text == clean_html(body).text and SENTINEL in text
    assert record.bytes == len(body) and isinstance(record.bytes, int)
    assert record.content_sha256 == hashlib.sha256(body).hexdigest()
    assert record.cleaned_text_sha256 == hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
    assert record.content_sha256 == record.content_sha256.lower()
    assert record.text_chars == len(text) and record.passage_count == 1
    assert record.cleaner_version == CLEANER_VERSION == "2"
    assert record.pdf_extractor_version is None
    assert record.segmenter_version == SEGMENTER_VERSION
    assert record.url == record.final_url == fake_server[0] + "/page"
    assert SENTINEL not in record.model_dump_json()


def test_pdf_snapshot_extractor_version_and_page_passages(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    body = make_text_pdf(
        [
            ["Fictional award supporting text is sufficiently long for extraction."],
            ["Fictional second page with additional supporting text and records."],
        ]
    )
    record = fetch_and_store(
        tmp_path, fake_server, body, slug="fictional-pdf", media="application/pdf"
    )
    assert (tmp_path / "copies/fictional-pdf.pdf").read_bytes() == body
    text = (tmp_path / "copies/fictional-pdf.txt").read_text(encoding="utf-8")
    assert record.format == "pdf" and record.text_chars == len(text) and record.passage_count == 2
    assert record.pdf_extractor_version == PDF_EXTRACTOR_VERSION == "1"
    assert record.cleaner_version is None and record.extraction_status == "ok"


@pytest.mark.parametrize(
    "body,extraction_status",
    [(b"not a PDF", "invalid"), (make_text_pdf([[]]), "scanned_unsupported")],
)
def test_unsupported_pdf_is_explicit_not_silently_usable(
    tmp_path: Path, fake_server: FakeServer, body: bytes, extraction_status: str
) -> None:
    record = fetch_and_store(tmp_path, fake_server, body, media="application/pdf")
    assert record.extraction_status == extraction_status
    assert record.text_chars == record.passage_count == 0
    assert (tmp_path / "copies/fictional-award.txt").read_bytes() == b""


@pytest.mark.parametrize(
    "replacement,expected",
    [
        (b'<main data-nonce="two"><p>Fictional text is unchanged.</p></main>', "benign_raw_change"),
        (b"<main><p>Fictional text is changed.</p></main>", "content_changed"),
        (b'<main data-nonce="one"><p>Fictional text is unchanged.</p></main>', "unchanged"),
    ],
)
def test_raw_nonce_and_content_drift(
    tmp_path: Path, fake_server: FakeServer, replacement: bytes, expected: str
) -> None:
    old = fetch_and_store(
        tmp_path, fake_server, b'<main data-nonce="one"><p>Fictional text is unchanged.</p></main>'
    )
    new = fetch_and_store(tmp_path, fake_server, replacement)
    assert classify_drift(old, new).classification == expected


def test_cleaned_hash_normalizes_whitespace_but_not_case_or_digits(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    old = fetch_and_store(
        tmp_path, fake_server, b"<pre>Fictional award 2027\nTuition support.</pre>"
    )
    spaced = fetch_and_store(
        tmp_path, fake_server, b"<pre>Fictional award 2027 Tuition support.</pre>"
    )
    assert old.text_chars == spaced.text_chars  # LF vs space, different private text.
    assert old.cleaned_text_sha256 == spaced.cleaned_text_sha256
    assert classify_drift(old, spaced).classification == "benign_raw_change"
    for body in [
        b"<p>Fictional award 2026 Tuition support.</p>",
        b"<p>fictional award 2027 Tuition support.</p>",
    ]:
        edited = fetch_and_store(tmp_path, fake_server, body)
        assert classify_drift(old, edited).classification == "content_changed"


@pytest.mark.parametrize("tool", ["cleaner_version", "segmenter_version"])
def test_version_change_precedes_equal_cleaned_hashes(
    tmp_path: Path, fake_server: FakeServer, tool: str
) -> None:
    old = fetch_and_store(tmp_path, fake_server, b"<p>Fictional page text.</p>")
    new = old.model_copy(update={tool: "next", "content_sha256": "f" * 64})
    assert old.cleaned_text_sha256 == new.cleaned_text_sha256
    assert classify_drift(old, new).classification == "tool_version_changed"
    same_raw = classify_drift(old, old.model_copy(update={tool: "next"}))
    assert same_raw.classification == "tool_version_changed"
    assert same_raw.cleaned_text_changed is False


def test_pdf_extractor_version_drift(tmp_path: Path, fake_server: FakeServer) -> None:
    old = fetch_and_store(
        tmp_path,
        fake_server,
        make_text_pdf([["Sufficient fictional PDF text here."]]),
        media="application/pdf",
    )
    new = old.model_copy(update={"pdf_extractor_version": "2", "content_sha256": "e" * 64})
    assert classify_drift(old, new).classification == "tool_version_changed"
    assert (
        classify_drift(old, old.model_copy(update={"pdf_extractor_version": "next"})).classification
        == "tool_version_changed"
    )


@pytest.mark.parametrize("changed", [False, True])
def test_same_raw_cleaner_bump_reports_cleaned_hash_change(tmp_path: Path, changed: bool) -> None:
    result = FetchResult(
        url="https://example.invalid/page",
        status="ok",
        content=b"<p>Fictional content.</p>",
        content_type="text/html",
        fetched_at="2026-10-29T10:00:00Z",
    )
    old = snapshot_page(result, "fictional", snapshots_dir=tmp_path)
    new = old.model_copy(
        update={
            "cleaner_version": "next",
            "cleaned_text_sha256": "e" * 64 if changed else old.cleaned_text_sha256,
        }
    )
    drift = classify_drift(old, new)
    assert old.content_sha256 == new.content_sha256
    assert drift.classification == "tool_version_changed"
    assert drift.cleaned_text_changed is changed
    identical = classify_drift(old, old.model_copy(deep=True))
    assert identical.classification == "unchanged" and not identical.cleaned_text_changed


@pytest.mark.parametrize("changed", [False, True])
def test_refetch_prints_version_drift_for_identical_raw_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changed: bool,
) -> None:
    result = FetchResult(
        url="https://example.invalid/page",
        status="ok",
        content=b"<p>Fictional content.</p>",
        content_type="text/html",
        fetched_at="2026-10-29T10:00:00Z",
    )
    record = snapshot_page(result, "fictional", snapshots_dir=tmp_path / "copies")
    old = record.model_copy(
        update={
            "cleaner_version": "baseline",
            "cleaned_text_sha256": "e" * 64 if changed else record.cleaned_text_sha256,
        }
    )
    manifest = tmp_path / "manifest.json"
    write_manifest(SnapshotManifest(snapshots={old.slug: old}), manifest)
    before = manifest.read_bytes()
    write_source(tmp_path / "gold", old.slug, old.url)
    with Fetcher(tmp_path / "fetched", min_interval_seconds=0) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", lambda url: result)
        assert (
            cli.refetch(
                gold_dir=tmp_path / "gold",
                manifest_path=manifest,
                snapshots_dir=tmp_path / "copies",
                update_manifest=False,
                fetcher=fetcher,
            )
            == 0
        )
    output = capsys.readouterr().out
    assert (
        output.splitlines()[0]
        == "slug | status | drift class | old/new raw hash | old/new cleaned hash"
    )
    assert " | tool_version_changed | " in output and " | unchanged | " not in output
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("slug", ["../escape", "nested/name", "Bad_slug", "", "a\\b"])
def test_unsafe_slugs_rejected_before_writing(tmp_path: Path, slug: str) -> None:
    with pytest.raises(ValueError, match="slug"):
        snapshot_page(
            FetchResult(url="https://example.invalid", status="ok", content=b"x"),
            slug,
            snapshots_dir=tmp_path / "copies",
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status", ["blocked", "not_found", "network_error"])
def test_failed_fetch_has_no_snapshot(tmp_path: Path, status: Any) -> None:
    with pytest.raises(ValueError, match="fetch status"):
        snapshot_page(
            FetchResult(url="https://example.invalid", status=status),
            "fictional",
            snapshots_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        {"content_sha256": "0" * 64},
        {"fetched_at": None},
        {"fetched_at": "2026-10-24T12:00:00"},
        {"content_type": "image/png"},
    ],
)
def test_bad_fetch_metadata_rejected_without_slug_files(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    result = FetchResult(
        url="https://example.invalid/page",
        status="ok",
        content=b"<p>Text</p>",
        fetched_at="2026-10-24T12:00:00+00:00",
        content_type="text/html",
    )
    with pytest.raises(ValueError):
        snapshot_page(replace(result, **change), "fictional", snapshots_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_retrieval_date_comes_from_fetch_utc_not_clock(tmp_path: Path) -> None:
    result = FetchResult(
        url="https://example.invalid/page",
        status="ok",
        content=b"<p>Text</p>",
        fetched_at="2026-10-24T01:00:00+05:00",
        content_type="text/html",
    )
    record = snapshot_page(result, "fictional", snapshots_dir=tmp_path)
    assert record.retrieved_on == "2026-10-23"


def manifest_validator() -> Draft202012Validator:
    schema = json.loads(
        (ROOT / "eval/schema/snapshot-manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def test_public_manifest_is_schema_valid() -> None:
    data = json.loads((ROOT / "eval/manifest.json").read_text(encoding="utf-8"))
    manifest_validator().validate(data)
    SnapshotManifest.model_validate(data)


def test_manifest_schema_property_names_do_not_drift() -> None:
    schema = json.loads(
        (ROOT / "eval/schema/snapshot-manifest.schema.json").read_text(encoding="utf-8")
    )
    assert set(schema["properties"]) == set(SnapshotManifest.model_fields)
    assert set(schema["$defs"]["snapshot"]["properties"]) == set(SnapshotRecord.model_fields)


def test_manifest_schema_round_trip_and_no_page_content(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    record = fetch_and_store(tmp_path, fake_server, f"<p>{SENTINEL}</p>".encode())
    path = tmp_path / "manifest.json"
    manifest = SnapshotManifest(snapshots={record.slug: record})
    write_manifest(manifest, path)
    manifest_validator().validate(json.loads(path.read_text(encoding="utf-8")))
    assert load_manifest(path) == manifest
    assert SENTINEL not in path.read_text(encoding="utf-8")
    bad = record.model_dump() | {"text": SENTINEL}
    with pytest.raises(ValidationError):
        SnapshotRecord.model_validate(bad)
    with pytest.raises(SchemaValidationError):
        manifest_validator().validate({"schema_version": "0.1", "snapshots": {record.slug: bad}})
    with pytest.raises(ValidationError, match="key"):
        SnapshotManifest(snapshots={"wrong-slug": record})


def write_source(gold: Path, slug: str, url: str) -> None:
    gold.mkdir(parents=True, exist_ok=True)
    (gold / f"{slug}.json").write_text(
        json.dumps(
            {
                "program_slug": slug,
                "source": {"url": url},
                "notes": "SKELETON: synthetic test metadata.",
            }
        ),
        encoding="utf-8",
    )


def test_refetch_errors_report_per_slug_keep_baseline_and_continue(
    tmp_path: Path, fake_server: FakeServer, capsys: pytest.CaptureFixture[str]
) -> None:
    base, handler = fake_server
    gold, snapshots, manifest_path = (
        tmp_path / "gold",
        tmp_path / "copies",
        tmp_path / "manifest.json",
    )
    handler.routes = {
        "/robots.txt": (200, b"User-agent: *\nDisallow: /blocked\n"),
        "/blocked": (200, b"must never fetch"),
        "/network": None,
        "/ok": (200, f"<p>{SENTINEL}</p>".encode(), {"Content-Type": "text/html"}),
    }
    for slug, path in [
        ("one-blocked", "blocked"),
        ("two-missing", "404"),
        ("three-network", "network"),
        ("four-ok", "ok"),
    ]:
        write_source(gold, slug, f"{base}/{path}")
    write_source(gold, "_example-fictional", "https://example.invalid/do-not-fetch")
    before = {path: path.read_bytes() for path in gold.iterdir()}
    with Fetcher(tmp_path / "fetched", min_interval_seconds=0) as fetcher:
        code = cli.refetch(
            gold_dir=gold,
            snapshots_dir=snapshots,
            manifest_path=manifest_path,
            update_manifest=True,
            fetcher=fetcher,
        )
    assert code == 0
    output = capsys.readouterr()
    for status in ["blocked", "not_found", "network_error", "ok"]:
        assert f" | {status} | " in output.out
    assert "/blocked" not in handler.request_counts
    assert SENTINEL not in manifest_path.read_text(encoding="utf-8")
    assert set(load_manifest(manifest_path).snapshots) == {"four-ok"}
    assert before == {path: path.read_bytes() for path in gold.iterdir()}


def test_cli_no_manifest_update_unless_flag_and_drift_exit_zero(
    tmp_path: Path,
    fake_server: FakeServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base, handler = fake_server
    gold, copies, manifest_path = tmp_path / "gold", tmp_path / "copies", tmp_path / "manifest.json"
    write_source(gold, "fictional-award", base + "/page")
    handler.routes = {
        "/page": (200, b"<p>Fictional first text.</p>", {"Content-Type": "text/html"})
    }
    monkeypatch.setattr(cli, "Fetcher", lambda path: Fetcher(path, min_interval_seconds=0))
    args = [
        "--gold-dir",
        str(gold),
        "--manifest",
        str(manifest_path),
        "--snapshots-dir",
        str(copies),
    ]
    assert cli.main(args + ["--update-manifest"]) == 0
    baseline = manifest_path.read_bytes()
    handler.routes["/page"] = (200, b"<p>Fictional second text.</p>", {"Content-Type": "text/html"})
    assert cli.main(args) == 0
    assert manifest_path.read_bytes() == baseline
    assert "content_changed" in capsys.readouterr().out
    assert (copies / "fictional-award.html").exists()
    handler.routes["/page"] = (404, b"gone")
    assert cli.main(args + ["--update-manifest"]) == 0
    assert manifest_path.read_bytes() == baseline


def test_script_errors_exit_one_and_gold_directory_cannot_be_output(
    tmp_path: Path, fake_server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, handler = fake_server
    gold = tmp_path / "gold"
    write_source(gold, "fictional-award", base + "/page")
    handler.routes = {"/page": (200, b"binary content", {"Content-Type": "image/png"})}
    monkeypatch.setattr(cli, "Fetcher", lambda path: Fetcher(path, min_interval_seconds=0))
    args = ["--gold-dir", str(gold), "--manifest", str(tmp_path / "manifest.json")]
    assert cli.main(args + ["--snapshots-dir", str(gold)]) == 1
    assert handler.request_counts == {}
    assert cli.main(args + ["--snapshots-dir", str(tmp_path / "copies"), "--update-manifest"]) == 1
    assert not (tmp_path / "manifest.json").exists()
    assert cli.main(["--unknown-argument"]) == 1
    (gold / "fictional-award.json").write_text("{bad json", encoding="utf-8")
    assert cli.main(args + ["--snapshots-dir", str(tmp_path / "copies")]) == 1


def test_default_cli_preserves_frozen_hand_label_snapshots(
    tmp_path: Path, fake_server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, handler = fake_server
    snapshots = tmp_path / "eval/snapshots"
    snapshots.mkdir(parents=True)
    frozen = snapshots / "fictional-award.html"
    frozen.write_bytes(b"synthetic frozen hand-label original")
    write_source(tmp_path / "eval/gold", "fictional-award", base + "/page")
    handler.routes = {
        "/page": (200, b"<p>Refetched fictional content.</p>", {"Content-Type": "text/html"})
    }
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "SNAPSHOTS_DIR", snapshots)
    monkeypatch.setattr(cli, "MANIFEST_PATH", tmp_path / "eval/manifest.json")
    monkeypatch.setattr(cli, "Fetcher", lambda path: Fetcher(path, min_interval_seconds=0))
    assert cli.main([]) == 0
    assert frozen.read_bytes() == b"synthetic frozen hand-label original"
    assert (snapshots / "refetched/fictional-award.html").exists()
    assert not (tmp_path / "eval/manifest.json").exists()


def test_snapshots_are_git_ignored() -> None:
    assert "eval/snapshots/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
