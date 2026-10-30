"""Read labels and frozen bytes only; never fetch or write snapshots/gold."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from scholarscope.cleaner import clean_html
from scholarscope.fetcher import FetchResult
from scholarscope.pdf_text import extract_pdf_text
from scholarscope.schema import RequirementRecord, from_gold_label
from scholarscope.segmenter import SegmentedDocument, segment
from scholarscope.snapshots import SLUG_PATTERN, SnapshotManifest, load_manifest

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GoldLabel:
    slug: str
    record: RequirementRecord
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class SkippedLabel:
    slug: str
    reason: str


def _skeleton(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key in {"note", "notes"} and isinstance(item, str) and "SKELETON" in item.upper())
            or _skeleton(item)
            for key, item in value.items()
        )
    return isinstance(value, list) and any(_skeleton(item) for item in value)


def load_labels(
    directory: Path,
    slugs: list[str] | None = None,
    *,
    schema_path: Path = ROOT / "eval/schema/gold-label.schema.json",
) -> tuple[list[GoldLabel], list[SkippedLabel]]:
    """Underscore examples are never benchmark labels, even if explicitly selected."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    names = (
        sorted(set(slugs))
        if slugs is not None
        else sorted(p.stem for p in directory.glob("*.json") if not p.name.startswith("_"))
    )
    labels: list[GoldLabel] = []
    skipped: list[SkippedLabel] = []
    for slug in names:
        if not re.fullmatch(SLUG_PATTERN, slug):
            skipped.append(SkippedLabel(slug, "invalid slug or excluded fictional example"))
            continue
        try:
            raw = json.loads((directory / f"{slug}.json").read_text(encoding="utf-8"))
            if _skeleton(raw):
                skipped.append(SkippedLabel(slug, "SKELETON note: not labeled by hand"))
                continue
            if isinstance(raw, dict) and raw.get("labeler", {}).get("minutes_spent") == 0:
                skipped.append(SkippedLabel(slug, "minutes_spent == 0: not labeled by hand"))
                continue
            if list(validator.iter_errors(raw)):
                raise ValueError("invalid gold schema")
            if raw["program_slug"] != slug:
                raise ValueError("gold slug does not match filename")
            if (raw["deadlines_status"] == "present" and not raw["deadlines"]) or (
                raw["deadlines_status"] in {"absent", "in_linked_document"} and raw["deadlines"]
            ):
                raise ValueError("inconsistent gold deadline set")
            record = from_gold_label(raw)
            labels.append(GoldLabel(slug, record, raw))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            skipped.append(SkippedLabel(slug, "missing/unreadable or invalid gold label"))
    return labels, skipped


def local_input(
    label: GoldLabel,
    directory: Path,
    *,
    manifest: SnapshotManifest | None = None,
) -> tuple[FetchResult, SegmentedDocument, str]:
    """Use slug or fetched/<hash> bytes; require exact frozen raw hash.

    Snapshot metadata supplies a final URL only when its raw hash matches gold.
    No cleaned-text sidecar is trusted; current tools derive text in memory.
    Layout is an observable static bucket, not a guess about JS/multi-page sites.
    """
    source = label.record.source
    paths = [
        directory / f"{label.slug}.{source.format}",
        directory / "fetched" / f"{source.content_sha256}.{source.format}",
    ]
    candidates = [p for p in paths if p.is_file()]
    if not candidates:
        raise ValueError("local snapshot missing")
    data: bytes | None = None
    for path in candidates:
        candidate = path.read_bytes()
        if hashlib.sha256(candidate).hexdigest() == source.content_sha256:
            data = candidate
            break
    if data is None:
        raise ValueError("local snapshot hash differs from frozen gold")
    metadata = manifest.snapshots.get(label.slug) if manifest else None
    final_url = (
        metadata.final_url
        if metadata and metadata.content_sha256 == source.content_sha256
        else source.url
    )
    fetch = FetchResult(
        url=source.url,
        final_url=final_url,
        status="ok",
        content=data,
        content_sha256=source.content_sha256,
        content_type="text/html" if source.format == "html" else "application/pdf",
    )
    if source.format == "html":
        cleaned = clean_html(data, base_url=final_url)
        doc = segment(cleaned)
        layout = (
            "html_table" if any("/tr[" in span.node_path for span in cleaned.offset_map) else "html"
        )
    else:
        pdf = extract_pdf_text(data)
        doc = segment(pdf)
        layout = "pdf_multi_page" if pdf.page_count > 1 else "pdf"
    return fetch, doc, layout


def optional_manifest(path: Path) -> SnapshotManifest:
    return load_manifest(path) if path.exists() else SnapshotManifest()
