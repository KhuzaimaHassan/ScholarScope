"""Manual local-snapshot extraction; never fetches or changes snapshots/labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scholarscope.fetcher import FetchResult
from scholarscope.llm.config import LLMConfig, build_client
from scholarscope.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--snapshots-dir", type=Path, default=ROOT / "eval/snapshots")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug):
        parser.error("invalid slug")
    candidates = [args.snapshots_dir / f"{args.slug}.{ext}" for ext in ("html", "pdf")]
    existing = [path for path in candidates if path.is_file()]
    if len(existing) != 1:
        parser.error("expected exactly one local .html or .pdf file for the slug")
    path = existing[0]
    try:
        data = path.read_bytes()
        # Original retrieval URL/date are unavailable without a sidecar. Do not
        # read gold labels, invent an HTTP URL, or claim the mtime is retrieval.
        fetch = FetchResult(
            url=path.resolve().as_uri(),
            status="ok",
            final_url=path.resolve().as_uri(),
            content_type="text/html" if path.suffix == ".html" else "application/pdf",
            fetched_at=datetime.now(UTC).isoformat(),
            content_sha256=hashlib.sha256(data).hexdigest(),
            content=data,
        )
        client = build_client(LLMConfig.from_env())
        try:
            result = run_pipeline(fetch, client)
        finally:
            client.close()
    except (OSError, ValueError):
        print("Local extraction failed: check the snapshot and configuration.", file=sys.stderr)
        return 1
    if result.record is not None:
        print(result.record.model_dump_json(indent=2))
    print(
        json.dumps(
            {
                "status": result.status,
                "verification": {str(k): v for k, v in result.verification.totals.items()}
                if result.verification
                else None,
                "failed_groups": result.extraction.failed_groups if result.extraction else [],
                "rejected_items": len(result.extraction.rejected_items) if result.extraction else 0,
                "suspicious_passages": [asdict(item) for item in result.suspicious_passages],
            }
        )
    )
    return 0 if result.status in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
