"""Fictional hand-specified labels, tmp_path bytes and FakeClient only; no sockets."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import socket
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from reportlab.pdfgen.canvas import Canvas

from scholarscope.eval.loader import GoldLabel, SkippedLabel, load_labels, local_input
from scholarscope.eval.metrics import ProgramEvaluation, aggregate, score_program
from scholarscope.eval.normalize import canonical, normalize_value
from scholarscope.eval.report import audit_sample, build_report, markdown, write_report
from scholarscope.eval.runner import evaluate
from scholarscope.llm.base import StructuredRequest, Usage
from scholarscope.llm.cache import FileCache
from scholarscope.llm.fake import FakeClient
from scholarscope.pipeline import run_pipeline
from scholarscope.schema import from_gold_label
from scholarscope.snapshots import SnapshotManifest, snapshot_page

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts/run_eval.py")
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
TITLE = "Fictional Aurora Scholarship"
URL = "https://fictional.invalid/apply"
LINES = [
    TITLE,
    "Fictional Institute hosts master students.",
    "Stipend: 500 USD per month.",
    "Submit a transcript and two academic references.",
    f"Apply online: {URL}",
    "Application deadline: 1 May 2027 at 23:59 UTC.",
    "Minimum GPA: 3.5 on a 4.0 scale.",
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("network prohibited in evaluation tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def claim(value: Any, quote: str) -> dict[str, Any]:
    return {"status": "present", "value": value, "evidence": [{"quote": quote}], "linked_url": None}


def gold_data(data: bytes, *, slug: str = "fictional-aurora", pdf: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "program_slug": slug,
        "slot": {"family": "Fictional", "number": 1},
        "source": {
            "url": "https://fictional.invalid/scholarship",
            "retrieved_on": "2026-10-30",
            "content_sha256": hashlib.sha256(data).hexdigest(),
            "format": "pdf" if pdf else "html",
            "page_state": "open",
            "language": "en",
            "is_mirror": False,
            "owner_org": "Fictional Institute",
        },
        "labeler": {
            "id": "fictional-test-owner",
            "pass": 1,
            "labeled_on": "2026-10-30",
            "minutes_spent": 5,
        },
        "fields": {
            "program_name": claim(TITLE, LINES[0]),
            "institution": claim("Fictional Institute", LINES[1]),
            "degree_levels": claim(["master"], LINES[1]),
            "funding_coverage": claim(
                [{"item": "stipend", "amount": 500, "currency": "USD", "period": "month"}], LINES[2]
            ),
            "required_documents": claim(["transcript"], LINES[3]),
            "recommenders": claim({"count_min": 2, "count_max": 2, "type": "academic"}, LINES[3]),
            "application_link": claim(URL, LINES[4]),
        },
        "deadlines_status": "present",
        "deadlines": [
            {
                "label": "Application",
                "type": "application",
                "cycle_year": 2027,
                "date": "2027-05-01",
                "time": "23:59",
                "timezone": "UTC",
                "rolling": False,
                "status": "present",
                "evidence": [{"quote": LINES[5]}],
            }
        ],
        "conditions": [
            {
                "kind": "min_gpa",
                "value": {"value": 3.5, "scale": 4.0},
                "required": True,
                "applies_to": None,
                "evidence": [{"quote": LINES[6]}],
            }
        ],
    }


def html_data() -> bytes:
    return (
        "<main><h1>" + LINES[0] + "</h1>" + "".join(f"<p>{s}</p>" for s in LINES[1:]) + "</main>"
    ).encode()


def payload(request: StructuredRequest[Any], gold: dict[str, Any]) -> dict[str, Any]:
    group = request.prompt_version.split("-", 1)[0]
    names = {
        "identity": ("program_name", "institution", "application_link", "degree_levels"),
        "funding": ("funding_coverage",),
        "documents": ("required_documents", "recommenders"),
    }
    if group in names:
        result = {name: deepcopy(gold["fields"][name]) for name in names[group]}
        for field in result.values():
            field.setdefault("notes", None)
            field.setdefault("linked_url", None)
    elif group == "deadlines":
        result = {
            "deadlines_status": gold["deadlines_status"],
            "deadlines": deepcopy(gold["deadlines"]),
            "linked_url": None,
            "notes": None,
        }
    else:
        result = {"conditions": deepcopy(gold["conditions"])}
    if group == "funding" and result["funding_coverage"]["value"]:
        for item in result["funding_coverage"]["value"]:
            for optional in ("amount", "amount_max", "currency", "period", "note"):
                item.setdefault(optional, None)
    if group in {"deadlines", "conditions"}:
        for item in result[group]:
            item.setdefault("notes", None)

    def evidence_ids(value: Any) -> None:
        if isinstance(value, dict):
            if "quote" in value:
                value["passage_id"] = next(
                    pid for pid, text in request.untrusted_passages if value["quote"] in text
                )
            for child in value.values():
                evidence_ids(child)
        elif isinstance(value, list):
            for child in value:
                evidence_ids(child)

    evidence_ids(result)
    return result


def setup(tmp_path: Path, *, pdf: bool = False) -> tuple[GoldLabel, Any, Any, str]:
    if pdf:
        stream = BytesIO()
        canvas = Canvas(stream, invariant=1)
        for i, line in enumerate(LINES):
            canvas.drawString(30, 700 - 25 * i, line)
        canvas.save()
        data = stream.getvalue()
    else:
        data = html_data()
    raw = gold_data(data, pdf=pdf)
    label = GoldLabel(raw["program_slug"], from_gold_label(raw), raw)
    (tmp_path / f"{label.slug}.{'pdf' if pdf else 'html'}").write_bytes(data)
    fetch, doc, layout = local_input(label, tmp_path)
    return label, fetch, doc, layout


def program(tmp_path: Path, mutate: Any = None, *, pdf: bool = False) -> ProgramEvaluation:
    label, fetch, doc, layout = setup(tmp_path, pdf=pdf)

    def response(request: StructuredRequest[Any]) -> str:
        result = payload(request, label.raw)
        if mutate:
            mutate(request.prompt_version.split("-", 1)[0], result)
        return json.dumps(result)

    client = FakeClient(responses=[response] * 5)
    pipeline = run_pipeline(fetch, client, source=label.record.source)
    assert pipeline.status == "ok" or mutate is not None
    return ProgramEvaluation(label, pipeline, doc, layout, 0.25)


@pytest.mark.parametrize("pdf", [False, True])
def test_perfect(tmp_path: Path, pdf: bool) -> None:
    p = program(tmp_path, pdf=pdf)
    result = aggregate([score_program(p)])
    for metric in (result["fields"], result["deadlines"]):
        assert metric["precision"] == metric["recall"] == metric["f1"] == 1
        assert metric["decision_accuracy"] == 1
        assert metric["excluded"] == 0
    assert result["deadline_set_status"]["rate"] == result["evidence_presence"]["rate"] == 1
    assert not result["dangerous_errors"] and not result["verifier_bugs"]
    assert all(item["decision_accuracy"] == 1 for item in result["per_field"].values())


@pytest.mark.parametrize("bad_quote", [False, True])
def test_wrong_value_and_verification(tmp_path: Path, bad_quote: bool) -> None:
    def mutate(group: str, result: dict[str, Any]) -> None:
        if group == "identity":
            result["program_name"]["value"] = "Fabricated scholarship name"
            if bad_quote:
                result["program_name"]["evidence"][0]["quote"] = (
                    "This quote is fabricated entirely."
                )

    scored = score_program(program(tmp_path, mutate))
    assert len(scored["dangerous_errors"]) == (0 if bad_quote else 1)
    assert scored["fields"]["program_name"]["fp"] == 1
    assert scored["fields"]["program_name"]["fn"] == 1
    if bad_quote:
        assert scored["abstentions"]["by_reason"]["unverified"]["agrees"] == 0


def test_failed_group_excluded(tmp_path: Path) -> None:
    label, fetch, doc, layout = setup(tmp_path)
    client = FakeClient(
        responses=["invalid"] * 3 + [lambda r: json.dumps(payload(r, label.raw))] * 4
    )
    pipeline = run_pipeline(fetch, client, source=label.record.source)
    result = score_program(ProgramEvaluation(label, pipeline, doc, layout, 0))
    totals = aggregate([result])
    assert totals["fields"]["excluded"] == 4
    assert totals["fields"]["fp"] == totals["fields"]["fn"] == 0
    assert result["failed_groups"] == [
        {"slug": label.slug, "group": "identity", "status": "invalid_output"}
    ]
    assert result["abstentions"]["excluded"] == 4


def test_url_rejection_excluded_valid_siblings_kept(tmp_path: Path) -> None:
    def mutate(group: str, result: dict[str, Any]) -> None:
        if group == "identity":
            result["application_link"]["value"] = "https://fictional.invalid/not-on-page"

    result = score_program(program(tmp_path, mutate))
    assert result["fields"]["application_link"]["excluded"] == 1
    assert result["fields"]["program_name"]["tp"] == 1
    assert result["rejected_items"][0]["reason"] == "URL_NOT_ON_PAGE"


@pytest.mark.parametrize(
    "change",
    [{"notes": "prefix SKELETON suffix"}, {"labeler": {"minutes_spent": 0}}, {"nested": True}],
)
def test_skip_skeletons(tmp_path: Path, change: dict[str, Any]) -> None:
    raw = gold_data(html_data())
    if "nested" in change:
        raw["fields"]["program_name"]["notes"] = "unfinished SKELETON"
    elif "labeler" in change:
        raw["labeler"].update(change["labeler"])
    else:
        raw.update(change)
    (tmp_path / "fictional-aurora.json").write_text(json.dumps(raw), encoding="utf-8")
    labels, skipped = load_labels(tmp_path)
    assert not labels and len(skipped) == 1
    assert "SKELETON" in skipped[0].reason or "minutes_spent" in skipped[0].reason
    client = FakeClient()
    programs, _ = evaluate(
        client,
        gold_dir=tmp_path,
        snapshots_dir=tmp_path / "missing",
        manifest_path=tmp_path / "missing.json",
    )
    assert not programs and not client.requests


@pytest.mark.parametrize(
    ("left", "right", "field"),
    [
        ("1 May 2027", "2027-05-01", "date"),
        ("May 1, 2027", "2027-05-01", "date"),
        ("11:59 PM", "23:59", "time"),
        ("JST", "Asia/Tokyo", "timezone"),
        ("Beijing time", "Asia/Shanghai", "timezone"),
        ("CET", "UTC+01:00", "timezone"),
        (["MSc"], ["master"], "degree_levels"),
        ({"value": 3.5, "scale": 4.0}, {"scale": 4, "value": 3.5}, "min_gpa"),
        (
            [{"item": "stipend", "amount": 500, "currency": "USD", "period": "month"}],
            [
                {
                    "period": "month",
                    "currency": "USD",
                    "amount": 500.0,
                    "item": "stipend",
                    "note": None,
                }
            ],
            "funding_coverage",
        ),
    ],
)
def test_symmetric_normalization(left: Any, right: Any, field: str) -> None:
    assert canonical(left, field=field) == canonical(right, field=field)
    assert normalize_value(normalize_value(left, field=field), field=field) == normalize_value(
        left, field=field
    )


@pytest.mark.parametrize(
    ("left", "right", "field"),
    [
        ("1 May", "2027-05-01", "date"),
        ("05/06/2027", "2027-05-06", "date"),
        ("midnight", "00:00", "time"),
        ("Graduate", "master", "degree_levels"),
        ({"value": 3.5, "scale": 4}, {"value": 8.75, "scale": 10}, "min_gpa"),
        (
            {"amount": 500, "currency": "USD"},
            {"amount": 500, "currency": "EUR"},
            "funding_coverage",
        ),
        (
            {"amount": 6000, "period": "year"},
            {"amount": 500, "period": "month"},
            "funding_coverage",
        ),
        ({"amount_max": 500}, {"amount": 500}, "funding_coverage"),
    ],
)
def test_no_guessing_or_conversion(left: Any, right: Any, field: str) -> None:
    assert canonical(left, field=field) != canonical(right, field=field)


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2027-05-02"},
        {"type": "document"},
        {"cycle_year": 2028},
        {"time": "22:59"},
        {"timezone": "UTC+01:00"},
        {"rolling": True, "date": None},
        {"status": "ambiguous", "date": None},
    ],
)
def test_deadline_dimensions(tmp_path: Path, changes: dict[str, Any]) -> None:
    def mutate(group: str, result: dict[str, Any]) -> None:
        if group == "deadlines":
            result["deadlines"][0].update(changes)

    result = score_program(program(tmp_path, mutate))
    assert result["deadlines"]["fp"] == result["deadlines"]["fn"] == 1
    assert result["deadlines"]["exact"] == 0
    assert result["dangerous_errors"][0]["field"] == "deadlines[0]"


def test_rolling_and_set_status(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record is not None
    gold = deepcopy(p.gold.raw)
    gold["deadlines"][0].update(rolling=True, date=None, time=None, timezone=None)
    label = replace(p.gold, raw=gold, record=from_gold_label(gold))
    record = p.pipeline.record.model_copy(deep=True)
    record.deadlines[0].rolling = True
    record.deadlines[0].date = record.deadlines[0].time = record.deadlines[0].timezone = None
    result = score_program(replace(p, gold=label, pipeline=replace(p.pipeline, record=record)))
    assert result["deadlines"]["tp"] == 1 and result["deadlines"]["exact"] == 1
    record.deadlines_status = "ambiguous"
    result = score_program(replace(p, gold=label, pipeline=replace(p.pipeline, record=record)))
    assert result["deadline_set_status"]["matches"] == result["deadlines"]["exact"] == 0


def test_rejected_deadline_excludes_set(tmp_path: Path) -> None:
    def mutate(group: str, result: dict[str, Any]) -> None:
        if group == "deadlines":
            bad = deepcopy(result["deadlines"][0])
            bad.update(label="Invalid candidate", time="12:30", timezone=None)
            result["deadlines"].append(bad)

    result = score_program(program(tmp_path, mutate))
    assert result["deadlines"]["excluded"] == 1
    assert result["deadlines"]["excluded_gold_items"] == 1
    assert result["deadlines"]["excluded_predicted_items"] == 1
    assert result["deadlines"]["tp"] == result["deadlines"]["fn"] == 0
    assert result["rejected_items"][0]["index"] == 1


def test_presence_bug_loud_and_audit_deterministic(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record is not None
    rows = audit_sample([p], seed=123)
    assert rows == audit_sample([p], seed=123)
    assert all(row["supports_value (y/n)"] == row["notes"] == "" for row in rows)
    assert all(row["passage_context"] for row in rows)
    assert len(rows) == 9
    record = p.pipeline.record.model_copy(deep=True)
    record.fields.program_name.evidence[0].quote = "Fabricated verified quote"
    broken = replace(p, pipeline=replace(p.pipeline, record=record))
    report = build_report([broken], [], date="2026-10-30", git_commit="abc", seed=123)
    assert len(report["overall"]["verifier_bugs"]) == 1
    assert "VERIFIER BUG" in markdown(report)


def test_audit_cap_and_order_independence(tmp_path: Path) -> None:
    p = program(tmp_path)
    programs = [replace(p, gold=replace(p.gold, slug=f"fictional-{i:02d}")) for i in range(10)]
    sample = audit_sample(programs, seed=17)
    assert len(sample) == 50
    assert sample == audit_sample(list(reversed(programs)), seed=17)
    assert sample != audit_sample(programs, seed=18)


def test_report_provenance_and_artifacts(tmp_path: Path) -> None:
    p = program(tmp_path)
    report = build_report(
        [p], [SkippedLabel("unfinished", "SKELETON")], date="2026-10-30", git_commit="a" * 40
    )
    assert report["labels_used"] == [p.gold.slug]
    assert report["labels_skipped"][0]["reason"] == "SKELETON"
    assert set(report["tool_versions"]) == {
        "cleaner",
        "pdf_extractor",
        "segmenter",
        "verifier",
        "rendering",
    }
    assert report["prompt_versions"] and report["model"] == ["fake-v1"]
    assert report["provider"] == ["fake"] and report["git_commit"] == "a" * 40
    assert report["overall"]["usage"]["input_tokens"]["unknown_programs"] == 1
    out = tmp_path / "reports/2026-10-30.json"
    write_report(report, [p], out)
    assert json.loads(out.read_text(encoding="utf-8")) == report
    assert "Field P" in out.with_suffix(".md").read_text(encoding="utf-8")
    rendered = out.with_suffix(".md").read_text(encoding="utf-8")
    assert "Tool versions:" in rendered and "Prompt versions:" in rendered
    assert "fake-v1" in rendered and "Labels used:" in rendered
    with (out.parent / "2026-10-30-audit.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and rows[0]["supports_value (y/n)"] == ""


def test_cli_read_only_without_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_send(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("offline cache miss attempted model generation")

    monkeypatch.setattr(FakeClient, "_send", no_send)
    data = html_data()
    gold_dir, snapshots = tmp_path / "gold", tmp_path / "snapshots"
    gold_dir.mkdir()
    snapshots.mkdir()
    (gold_dir / "fictional-aurora.json").write_text(json.dumps(gold_data(data)), encoding="utf-8")
    (snapshots / "fictional-aurora.html").write_bytes(data)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "fake-v1")
    monkeypatch.setenv("LLM_CACHE_MODE", "off")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cache = tmp_path / "no-cache"
    out = tmp_path / "results.json"
    assert (
        cli.main(
            [
                "--all-labeled",
                "--gold-dir",
                str(gold_dir),
                "--snapshots-dir",
                str(snapshots),
                "--manifest",
                str(tmp_path / "none.json"),
                "--cache-dir",
                str(cache),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mode"] == "read_only" and not report["cache_directory_exists"]
    assert len(report["overall"]["failed_groups"]) == 5
    assert {g["status"] for g in report["overall"]["failed_groups"]} == {"unavailable"}
    assert report["overall"]["fields"]["excluded"] == 8
    assert report["overall"]["fields"]["recall"] is None
    assert not cache.exists()


def test_cache_replay_identical_metrics(tmp_path: Path) -> None:
    label, fetch, doc, layout = setup(tmp_path)
    cache_dir = tmp_path / "cache"
    client = FakeClient(
        cache=FileCache(cache_dir), responses=[lambda r: json.dumps(payload(r, label.raw))] * 5
    )
    run_pipeline(fetch, client, source=label.record.source)
    replay = FakeClient(cache=FileCache(cache_dir, mode="read_only"))
    first = run_pipeline(fetch, replay, source=label.record.source)
    second = run_pipeline(fetch, replay, source=label.record.source)
    assert replay.calls == 0
    a = score_program(ProgramEvaluation(label, first, doc, layout, 1))
    b = score_program(ProgramEvaluation(label, second, doc, layout, 1))
    assert a == b and not a["failed_groups"]


def test_manifest_final_url_and_hash_lookup(tmp_path: Path) -> None:
    label, fetch, doc, _ = setup(tmp_path)
    metadata = snapshot_page(
        replace(
            fetch, fetched_at="2026-10-30T10:00:00Z", final_url="https://fictional.invalid/moved"
        ),
        label.slug,
        snapshots_dir=tmp_path / "private",
    )
    manifest = SnapshotManifest(snapshots={label.slug: metadata})
    loaded, _, _ = local_input(label, tmp_path, manifest=manifest)
    assert loaded.final_url == metadata.final_url
    named = tmp_path / f"{label.slug}.html"
    hashed = tmp_path / "fetched" / f"{metadata.content_sha256}.html"
    hashed.parent.mkdir()
    named.rename(hashed)
    assert local_input(label, tmp_path)[1] == doc
    hashed.write_bytes(b"changed fictional bytes")
    with pytest.raises(ValueError, match="hash differs"):
        local_input(label, tmp_path)


def test_known_usage(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.extraction is not None
    p = replace(
        p,
        pipeline=replace(
            p.pipeline,
            extraction=replace(
                p.pipeline.extraction, usage=Usage(input_tokens=20, output_tokens=10)
            ),
        ),
    )
    result = aggregate([score_program(p)])
    assert result["usage"]["input_tokens"]["median_known"] == 20
    assert result["median_seconds"] == 0.25


def test_reports_ignored_and_protected(tmp_path: Path) -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "eval/reports/*" in ignored and "!eval/reports/.gitkeep" in ignored
    for path in (ROOT / "eval/gold/do-not-write.json", ROOT / "eval/snapshots/do-not-write.json"):
        with pytest.raises(ValueError, match="must not overwrite"):
            write_report({}, [], path)
        assert not path.exists()


STATUSES = ("present", "absent", "ambiguous", "in_linked_document")


@pytest.mark.parametrize("gold_status", STATUSES)
@pytest.mark.parametrize("pred_status", STATUSES)
def test_explicit_status_confusion(tmp_path: Path, gold_status: str, pred_status: str) -> None:
    p = program(tmp_path)
    assert p.pipeline.record is not None

    def state(status: str) -> dict[str, Any]:
        return {
            "status": status,
            "value": TITLE if status == "present" else None,
            "evidence": [{"quote": TITLE}] if status in {"present", "ambiguous"} else [],
            "linked_url": URL if status == "in_linked_document" else None,
        }

    raw = deepcopy(p.gold.raw)
    raw["fields"]["program_name"] = state(gold_status)
    label = replace(p.gold, raw=raw, record=from_gold_label(raw))
    record = p.pipeline.record.model_dump()
    record["fields"]["program_name"] = state(pred_status)
    predicted = type(p.pipeline.record).model_validate(record)
    scored = score_program(replace(p, gold=label, pipeline=replace(p.pipeline, record=predicted)))
    counts = scored["fields"]["program_name"]
    assert counts["confusion"] == {f"{gold_status}->{pred_status}": 1}
    assert counts["exact"] == int(gold_status == pred_status)
    assert counts["tp"] == int(gold_status == pred_status == "present")
    assert counts["fp"] == int(pred_status == "present" and gold_status != "present")
    assert counts["fn"] == int(gold_status == "present" and pred_status != "present")


def test_linked_target_mismatch_not_status_match(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record is not None
    raw = deepcopy(p.gold.raw)
    raw["fields"]["program_name"] = {
        "status": "in_linked_document",
        "value": None,
        "evidence": [],
        "linked_url": URL,
    }
    record = p.pipeline.record.model_dump()
    record["fields"]["program_name"] = {
        **raw["fields"]["program_name"],
        "linked_url": URL + "-other",
    }
    p = replace(
        p,
        gold=replace(p.gold, raw=raw, record=from_gold_label(raw)),
        pipeline=replace(p.pipeline, record=type(p.pipeline.record).model_validate(record)),
    )
    assert score_program(p)["fields"]["program_name"]["exact"] == 0


def test_deadline_unverified_retained_correct_value(tmp_path: Path) -> None:
    def mutate(group: str, result: dict[str, Any]) -> None:
        if group == "deadlines":
            result["deadlines"][0]["evidence"][0]["quote"] = "A fabricated deadline sentence"

    scored = score_program(program(tmp_path, mutate))
    assert not scored["dangerous_errors"]
    assert scored["deadlines"]["tp"] == 1
    assert scored["abstentions"]["by_reason"]["deadlines:unverified"] == {
        "count": 1,
        "agrees": 0,
        "retained_value_correct": 1,
    }


def test_empty_denominators_and_per_layout_counts(tmp_path: Path) -> None:
    assert aggregate([])["fields"]["f1"] is None
    assert aggregate([])["evidence_presence"]["rate"] is None
    p = program(tmp_path)
    programs = [p, replace(p, layout="html_table", gold=replace(p.gold, slug="other-fictional"))]
    report = build_report(programs, [], date="2026-10-30", git_commit="test")
    assert report["overall"]["programs"] == 2
    assert report["overall"]["fields"]["tp"] == 16
    assert report["per_layout"]["html"]["programs"] == 1
    assert report["per_layout"]["html_table"]["fields"]["tp"] == 8
    assert report["overall"]["dangerous_error_rate"]["rate"] == 0


def test_loader_skips_invalid_missing_and_fictional_examples(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("not JSON", encoding="utf-8")
    raw = gold_data(html_data(), slug="empty-deadline")
    raw["deadlines"] = []
    (tmp_path / "empty-deadline.json").write_text(json.dumps(raw), encoding="utf-8")
    labels, skipped = load_labels(
        tmp_path, ["bad", "missing", "_example-fictional", "../escape", "empty-deadline"]
    )
    assert not labels and len(skipped) == 5


def test_snapshot_missing_skipped_without_client_call(tmp_path: Path) -> None:
    raw = gold_data(html_data())
    (tmp_path / "fictional-aurora.json").write_text(json.dumps(raw), encoding="utf-8")
    client = FakeClient()
    programs, skipped = evaluate(
        client, gold_dir=tmp_path, snapshots_dir=tmp_path, manifest_path=tmp_path / "manifest.json"
    )
    assert not programs and not client.requests
    assert "snapshot" in skipped[0].reason


def test_report_custom_input_protection(tmp_path: Path) -> None:
    private = tmp_path / "private"
    with pytest.raises(ValueError, match="must not overwrite"):
        write_report({}, [], private / "gold.json", protected_dirs=(private,))
    assert not private.exists()


def test_normalized_evidence_checked_independently(tmp_path: Path) -> None:
    def mutate(group: str, result: dict[str, Any]) -> None:
        if group == "identity":
            result["institution"]["evidence"][0]["quote"] = LINES[1].replace(" ", "\u00a0")

    scored = score_program(program(tmp_path, mutate))
    assert not scored["verifier_bugs"]
    assert scored["evidence_presence"]["checked"] == scored["evidence_presence"]["found"] == 9


def test_deadline_multiset_order_independent_cycles(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record is not None
    raw = deepcopy(p.gold.raw)
    other = deepcopy(raw["deadlines"][0])
    other.update(cycle_year=2028, date="2028-05-01")
    raw["deadlines"].append(other)
    record = p.pipeline.record.model_copy(deep=True)
    second = record.deadlines[0].model_copy(update={"cycle_year": 2028, "date": "2028-05-01"})
    record.deadlines = [second, *record.deadlines]
    scored = score_program(
        replace(
            p,
            gold=replace(p.gold, raw=raw, record=from_gold_label(raw)),
            pipeline=replace(p.pipeline, record=record),
        )
    )
    assert scored["deadlines"]["tp"] == 2
    assert scored["deadlines"]["exact"] == 1


def test_unsupported_pdf_no_client_and_all_excluded(tmp_path: Path) -> None:
    raw = gold_data(b"not a PDF", pdf=True)
    (tmp_path / "fictional-aurora.json").write_text(json.dumps(raw), encoding="utf-8")
    (tmp_path / "fictional-aurora.pdf").write_bytes(b"not a PDF")
    client = FakeClient()
    programs, skipped = evaluate(
        client, gold_dir=tmp_path, snapshots_dir=tmp_path, manifest_path=tmp_path / "manifest.json"
    )
    assert not skipped and not client.requests
    result = aggregate([score_program(programs[0])])
    assert result["fields"]["excluded"] == 8
    assert result["deadlines"]["excluded"] == 1
    assert result["fields"]["recall"] is None


def test_runner_latency_and_input_files_read_only(tmp_path: Path) -> None:
    data = html_data()
    raw = gold_data(data)
    label_path = tmp_path / "fictional-aurora.json"
    snapshot_path = tmp_path / "fictional-aurora.html"
    label_path.write_text(json.dumps(raw), encoding="utf-8")
    snapshot_path.write_bytes(data)
    before = {p: p.read_bytes() for p in (label_path, snapshot_path)}
    client = FakeClient(responses=[lambda r: json.dumps(payload(r, raw))] * 5)
    ticks = iter([10.0, 12.5])
    programs, skipped = evaluate(
        client,
        gold_dir=tmp_path,
        snapshots_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        clock=lambda: next(ticks),
    )
    assert not skipped and programs[0].elapsed_seconds == 2.5
    assert {p: p.read_bytes() for p in before} == before
    assert set(tmp_path.iterdir()) == {label_path, snapshot_path}


def test_field_level_presence_abstention_danger_and_confidence(tmp_path: Path) -> None:
    p = program(tmp_path)
    assert p.pipeline.record is not None
    record = p.pipeline.record.model_copy(deep=True)
    record.fields.program_name.value = "Wrong fictional title"
    record.fields.program_name.confidence = 0.9
    record.fields.institution.confidence = 0.2
    result = aggregate([score_program(replace(p, pipeline=replace(p.pipeline, record=record)))])
    title = result["per_field"]["program_name"]
    assert title["evidence_presence"]["rate"] == 1
    assert title["dangerous_error_rate"]["rate"] == 1
    assert title["abstentions"]["count"] == 0
    assert result["confidence_diagnostic"]["pearson_correctness"] == -1
    assert result["confidence_diagnostic"]["count"] == 2
    assert record.fields.program_name.verification == "verified"  # diagnostics never change logic


def test_hash_addressed_fallback_when_slug_copy_drifted(tmp_path: Path) -> None:
    label, _, _, _ = setup(tmp_path)
    original = (tmp_path / f"{label.slug}.html").read_bytes()
    (tmp_path / f"{label.slug}.html").write_bytes(b"Changed private fictional page")
    hashed = tmp_path / "fetched" / f"{label.record.source.content_sha256}.html"
    hashed.parent.mkdir()
    hashed.write_bytes(original)
    loaded, _, _ = local_input(label, tmp_path)
    assert loaded.content == original
