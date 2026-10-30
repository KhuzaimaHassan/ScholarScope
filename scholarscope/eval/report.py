"""Private JSON/Markdown reports and human-support audit; no support judging."""

from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scholarscope.cleaner import CLEANER_VERSION
from scholarscope.eval.loader import ROOT, SkippedLabel
from scholarscope.eval.metrics import ProgramEvaluation, aggregate, owners, score_program
from scholarscope.extraction import PROMPT_VERSIONS
from scholarscope.llm.base import RENDERING_VERSION
from scholarscope.pdf_text import PDF_EXTRACTOR_VERSION
from scholarscope.segmenter import SEGMENTER_VERSION
from scholarscope.verifier import VERIFIER_VERSION


def audit_sample(
    programs: list[ProgramEvaluation], *, seed: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Sample claims, not quotes; every quote is retained for the human auditor.

    Context is private source text. CSVs are ignored, never publish automatically.
    Presence does not imply support; supports_value and notes start blank.
    """
    candidates: list[dict[str, Any]] = []
    for program in sorted(programs, key=lambda p: p.gold.slug):
        pipeline, doc = program.pipeline, program.document
        if pipeline.record is None:
            continue
        reports = pipeline.verification.items if pipeline.verification else ()
        for path, item in owners(pipeline.record):
            if item.verification != "verified":
                continue
            contexts = [
                doc.text[max(0, r.matched[0] - 150) : r.matched[1] + 150]
                for r in reports
                if r.owner_path == path and r.matched
            ]
            value = item.model_dump(mode="json", exclude={"evidence", "verification"})
            candidates.append(
                {
                    "slug": program.gold.slug,
                    "field": path,
                    "value": json.dumps(value, ensure_ascii=False, sort_keys=True),
                    "quote": json.dumps([e.quote for e in item.evidence], ensure_ascii=False),
                    "passage_context": "\n---\n".join(contexts),
                    "supports_value (y/n)": "",
                    "notes": "",
                }
            )
    chosen = random.Random(seed).sample(candidates, min(max(0, limit), 50, len(candidates)))
    return sorted(chosen, key=lambda row: (row["slug"], row["field"]))


def build_report(
    programs: list[ProgramEvaluation],
    skipped: list[SkippedLabel],
    *,
    date: str,
    git_commit: str,
    seed: int = 1729,
    mode: str = "read_only",
    cache_exists: bool = False,
) -> dict[str, Any]:
    scores = [score_program(p) for p in sorted(programs, key=lambda p: p.gold.slug)]
    audit = audit_sample(programs, seed=seed)
    return {
        "report_version": "1",
        "date": date,
        "git_commit": git_commit,
        "mode": mode,
        "cache_directory_exists": cache_exists,
        "tool_versions": {
            "cleaner": CLEANER_VERSION,
            "pdf_extractor": PDF_EXTRACTOR_VERSION,
            "segmenter": SEGMENTER_VERSION,
            "verifier": VERIFIER_VERSION,
            "rendering": RENDERING_VERSION,
        },
        "prompt_versions": dict(PROMPT_VERSIONS),
        "model": sorted(
            {
                str(p.pipeline.versions.get("model"))
                for p in programs
                if p.pipeline.versions.get("model") is not None
            }
        ),
        "provider": sorted(
            {
                str(p.pipeline.versions.get("provider"))
                for p in programs
                if p.pipeline.versions.get("provider") is not None
            }
        ),
        "labels_used": [p.gold.slug for p in sorted(programs, key=lambda p: p.gold.slug)],
        "labels_skipped": [asdict(p) for p in sorted(skipped, key=lambda p: p.slug)],
        "programs": scores,
        "overall": aggregate(scores),
        "per_layout": {
            layout: aggregate([p for p in scores if p["layout"] == layout])
            for layout in sorted({p["layout"] for p in scores})
        },
        "audit": {
            "seed": seed,
            "unit": "verified claim (all evidence quotes)",
            "sample_size": len(audit),
            "max_sample_size": 50,
        },
        "not_measured": [
            "eligibility agreement",
            "evidence support (human audit pending)",
            "held-out split enforcement",
            "CI regression gate",
            "live-model injection compliance",
            "currency cost (no price assumptions; tokens only)",
        ],
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _cell(value: Any) -> str:
    """Untrusted data stays inert table text, including HTML/Markdown characters."""
    import html

    text = html.escape(str(value), quote=True).replace("\n", " ").replace("\r", " ")
    for char in "\\`*[]()!|":
        text = text.replace(char, f"&#{ord(char)};")
    return text


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Evaluation results",
        "",
        f"Date (UTC): {report['date']}; commit: {report['git_commit']}",
        f"Dirty worktree: {report.get('git_dirty', 'not recorded by caller')}; mode: {_cell(report['mode'])}",
        "",
        "Tool versions: " + _cell(json.dumps(report["tool_versions"], sort_keys=True)),
        "Prompt versions: " + _cell(json.dumps(report["prompt_versions"], sort_keys=True)),
        "Observed models/providers: " + _cell(json.dumps([report["model"], report["provider"]])),
        "Configured model/provider: "
        + _cell(json.dumps([report.get("configured_model"), report.get("configured_provider")])),
        "Labels used: " + _cell(", ".join(report["labels_used"]) or "none"),
        "",
        "Presence is not support. n/a means an empty denominator, never a perfect score.",
        "Reports and audit context are private/ignored until owner approval to publish.",
        "",
        "| Layout | Programs | Field P | Field R | Field F1 | Decisions correct/n | Excluded field/set decisions | Deadline exact programs/n | Excluded deadline sets | Presence found/n | Verifier bugs | Dangerous errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in [("overall", report["overall"]), *report["per_layout"].items()]:
        f, d, e = metrics["fields"], metrics["deadlines"], metrics["evidence_presence"]
        lines.append(
            f"| {_cell(name)} | {metrics['programs']} | {_pct(f['precision'])} | "
            f"{_pct(f['recall'])} | {_pct(f['f1'])} | {f['exact']}/{f['decisions']} | "
            f"{f['excluded']} | {d['exact']}/{d['decisions']} | {d['excluded']} | "
            f"{e['found']}/{e['checked']} | {len(metrics['verifier_bugs'])} | "
            f"{len(metrics['dangerous_errors'])} |"
        )
    lines += [
        "",
        "## Per-field counts (overall)",
        "",
        "| Field | TP | FP | FN | P | R | F1 | Status/value correct/n | Excluded |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, entry in report["overall"]["per_field"].items():
        lines.append(
            f"| {name} | {entry['tp']} | {entry['fp']} | {entry['fn']} | "
            f"{_pct(entry['precision'])} | {_pct(entry['recall'])} | {_pct(entry['f1'])} | "
            f"{entry['exact']}/{entry['decisions']} | {entry['excluded']} |"
        )
    for key in (
        "deadlines",
        "deadline_set_status",
        "abstentions",
        "dangerous_error_rate",
        "confidence_diagnostic",
        "usage",
    ):
        lines += ["", f"{key}: `{json.dumps(report['overall'][key], sort_keys=True)}`"]
    lines += [
        "",
        f"Median seconds: {report['overall']['median_seconds']}",
        f"Audit seed: {report['audit']['seed']}; sample: {report['audit']['sample_size']}",
    ]
    for key, title in (
        ("failed_groups", "EXTRACTION FAILED (excluded)"),
        ("rejected_items", "Rejected items (excluded)"),
        ("verifier_bugs", "VERIFIER BUGS — investigate every miss"),
        ("dangerous_errors", "Dangerous verified-value errors"),
    ):
        entries = report["overall"][key]
        lines += ["", f"## {title}", "", "| Details |", "|---|"]
        lines += [
            f"| {_cell(json.dumps(entry, ensure_ascii=False, sort_keys=True))} |"
            for entry in entries
        ] or ["| None |"]
    lines += ["", "## Labels skipped", ""]
    lines += [
        f"- {_cell(item['slug'])}: {_cell(item['reason'])}" for item in report["labels_skipped"]
    ]
    lines += ["", "Not measured: " + "; ".join(report["not_measured"]), ""]
    return "\n".join(lines)


def write_report(
    report: dict[str, Any],
    programs: list[ProgramEvaluation],
    out: Path,
    *,
    protected_dirs: tuple[Path, ...] = (),
) -> None:
    """Write ignored report artifacts only; refuse protected labels/snapshots/cache."""
    target = out.resolve()
    if target.suffix != ".json":
        raise ValueError("report output must have .json extension")
    protected_paths = (
        ROOT / "eval/gold",
        ROOT / "eval/snapshots",
        ROOT / ".cache",
        *protected_dirs,
    )
    for protected in protected_paths:
        if target.is_relative_to(protected.resolve()):
            raise ValueError("report output must not overwrite gold, snapshots or cache")
    paths = [target, target.with_suffix(".md"), target.with_name(target.stem + "-audit.csv")]
    # Resolve all destinations, including existing symlinks, before writing any.
    for path in paths:
        if any(path.resolve().is_relative_to(p.resolve()) for p in protected_paths):
            raise ValueError("report output points into a protected directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    paths[1].write_text(markdown(report), encoding="utf-8")
    rows = audit_sample(programs, seed=report["audit"]["seed"])
    columns = (
        "slug",
        "field",
        "value",
        "quote",
        "passage_context",
        "supports_value (y/n)",
        "notes",
    )
    with paths[2].open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        # CSV text may be untrusted: use a text importer, never evaluate formulas.
        writer.writerows(rows)
