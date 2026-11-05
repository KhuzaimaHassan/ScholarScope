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
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scholarscope.extraction import SourceInfo
from scholarscope.fetcher import FetchResult
from scholarscope.llm.config import LLMConfig, build_client
from scholarscope.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parent.parent


def source_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(char.isspace() for char in value)
        ):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise argparse.ArgumentTypeError("source URL must be HTTP(S) without credentials") from None
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--snapshots-dir", type=Path, default=ROOT / "eval/snapshots")
    parser.add_argument("--source-url", type=source_url, help="User-supplied original HTTP(S) URL")
    parser.add_argument("--show-rejected", action="store_true", help="Include private raw items")
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
            source = (
                SourceInfo(
                    url=args.source_url,
                    retrieved_on=datetime.now(UTC).date().isoformat(),
                    content_sha256=hashlib.sha256(data).hexdigest(),
                    format="html" if path.suffix == ".html" else "pdf",
                    page_state="unknown",
                )
                if args.source_url
                else None
            )
            result = run_pipeline(fetch, client, source=source)
        finally:
            client.close()
    except (OSError, ValueError):
        print("Local extraction failed: check the snapshot and configuration.", file=sys.stderr)
        return 1
    if result.record is not None:
        print(result.record.model_dump_json(indent=2))
    extraction = result.extraction
    print(
        json.dumps(
            {
                "status": result.status,
                "verification": {str(k): v for k, v in result.verification.totals.items()}
                if result.verification
                else None,
                "failed_groups": result.extraction.failed_groups if result.extraction else [],
                "failure_details": {
                    group: asdict(detail) for group, detail in extraction.failure_details.items()
                }
                if extraction
                else {},
                "group_status": extraction.group_status if extraction else {},
                "group_latency_seconds": extraction.group_latency_seconds if extraction else {},
                "group_usage": {
                    group: usage.model_dump() for group, usage in extraction.group_usage.items()
                }
                if extraction
                else {},
                "rejected_items": len(result.extraction.rejected_items) if result.extraction else 0,
                "rejected_item_details": [
                    {
                        "group": item.group,
                        "index": item.index,
                        "reason": item.reason,
                        **({"raw_item": item.raw_item} if args.show_rejected else {}),
                    }
                    for item in extraction.rejected_items
                ]
                if extraction
                else [],
                "source_url_user_supplied": args.source_url is not None,
                "truncated": result.extraction.truncated if result.extraction else None,
                "passages_dropped": result.extraction.passages_dropped
                if result.extraction
                else None,
                "suspicious_passages": [asdict(item) for item in result.suspicious_passages],
            }
        )
    )
    return 0 if result.status in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
