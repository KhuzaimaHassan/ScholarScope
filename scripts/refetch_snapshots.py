"""Re-fetch metadata-only gold sources, respecting Fetcher robots and redirects.

Default output is private eval/snapshots/refetched, NOT frozen labeling copies.
Never read label claims for extraction, never write labels, never call an LLM.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from scholarscope.fetcher import Fetcher
from scholarscope.snapshots import (
    MANIFEST_PATH,
    SLUG_PATTERN,
    SNAPSHOTS_DIR,
    SnapshotManifest,
    SnapshotRecord,
    classify_drift,
    load_manifest,
    snapshot_page,
    write_manifest,
)


def read_sources(gold_dir: Path) -> list[tuple[str, str]]:
    """Read just slug/source.url, including skeletons; skip underscore examples."""
    if not gold_dir.is_dir():
        raise ValueError(f"gold directory not found: {gold_dir}")
    sources = []
    for path in sorted(gold_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        slug, url = data["program_slug"], data["source"]["url"]
        if not isinstance(slug, str) or not re.fullmatch(SLUG_PATTERN, slug) or slug != path.stem:
            raise ValueError(f"invalid slug or filename mismatch: {path.name}")
        if not isinstance(url, str) or not re.fullmatch(r"https?://\S+", url):
            raise ValueError(f"source URL must be HTTP(S): {path.name}")
        sources.append((slug, url))
    return sources


def _hash(record: SnapshotRecord | None, *, cleaned: bool = False) -> str:
    if record is None:
        return "-"
    return (record.cleaned_text_sha256 if cleaned else record.content_sha256)[:12]


def refetch(
    *,
    gold_dir: Path,
    manifest_path: Path,
    snapshots_dir: Path,
    update_manifest: bool,
    fetcher: Fetcher,
) -> int:
    protected = {gold_dir.resolve(), (ROOT / "eval/gold").resolve()}
    if any(
        path.resolve().is_relative_to(directory)
        for directory in protected
        for path in (snapshots_dir, manifest_path, fetcher.snapshot_dir)
    ):
        raise ValueError("output paths must never be inside a gold-label directory")
    sources = read_sources(gold_dir)
    manifest = load_manifest(manifest_path) if manifest_path.exists() else SnapshotManifest()
    records = dict(manifest.snapshots)
    script_errors = False
    print("slug | status | drift class | old/new raw hash | old/new cleaned hash")
    print("--- | --- | --- | --- | ---")
    for slug, url in sources:
        old = records.get(slug)
        new = None
        drift = "-"
        result = fetcher.fetch(url)
        status: str = result.status
        if result.status == "ok":
            try:
                new = snapshot_page(result, slug, snapshots_dir=snapshots_dir)
                drift = classify_drift(old, new).classification if old is not None else "new"
                records[slug] = new
                if new.extraction_status != "ok":
                    status = f"ok (PDF {new.extraction_status}; text unavailable)"
            except (ValueError, OSError) as exc:
                status = "script_error"
                script_errors = True
                print(f"{slug}: {exc}", file=sys.stderr)
        print(
            f"{slug} | {status} | {drift} | {_hash(old)}/{_hash(new)} | "
            f"{_hash(old, cleaned=True)}/{_hash(new, cleaned=True)}"
        )
        if result.error:
            print(f"{slug}: {result.error}", file=sys.stderr)
    if update_manifest and not script_errors:
        write_manifest(SnapshotManifest(snapshots=records), manifest_path)
    return 1 if script_errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-manifest", action="store_true")
    parser.add_argument("--snapshots-dir", type=Path, default=SNAPSHOTS_DIR / "refetched")
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "eval/gold")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    try:
        args = parser.parse_args(argv)
        with Fetcher(args.snapshots_dir / "fetched") as fetcher:
            return refetch(
                gold_dir=args.gold_dir,
                manifest_path=args.manifest,
                snapshots_dir=args.snapshots_dir,
                update_manifest=args.update_manifest,
                fetcher=fetcher,
            )
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"script error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
