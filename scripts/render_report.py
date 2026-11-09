"""Local snapshot -> inert HTML, cache-only by default; no fetching or automatic dotenv."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scholarscope.extraction import SourceInfo
from scholarscope.fetcher import FetchResult
from scholarscope.llm.config import LLMConfig, build_client
from scholarscope.pipeline import PipelineResult, run_pipeline
from scholarscope.report import render_report, safe_source_url

ROOT = Path(__file__).resolve().parents[1]


def source_url(value: str) -> str:
    if not safe_source_url(value):
        raise argparse.ArgumentTypeError(
            "source URL must be HTTP(S) without credentials or controls"
        )
    return value


def output_path(out: Path | None, slug: str) -> Path:
    """Resolve symlinks/traversal before writes; only two intentional output roots."""
    target = (out if out is not None else ROOT / "eval/reports" / f"{slug}-report.html").resolve()
    protected = [(ROOT / "eval/gold").resolve(), (ROOT / "eval/snapshots").resolve()]
    if any(target.is_relative_to(path) for path in protected):
        raise ValueError("report output cannot be inside gold or snapshots")
    allowed = [ROOT.resolve() / "eval/reports"]
    if out is not None:
        allowed.append(ROOT.resolve() / "docs/examples")
    if target.suffix.lower() != ".html" or not any(target.is_relative_to(path) for path in allowed):
        raise ValueError("output must be HTML in eval/reports or explicitly in docs/examples")
    return target


def synthetic_result() -> tuple[PipelineResult, datetime]:
    # The repository's standalone fictional test helper has no test-only dependencies.
    spec = importlib.util.spec_from_file_location(
        "report_fixtures", ROOT / "tests/report_fixtures.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("synthetic helper is unavailable")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper.synthetic_result(), helper.FIXED_NOW


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug")
    parser.add_argument("--snapshots-dir", type=Path, default=ROOT / "eval/snapshots")
    parser.add_argument("--source-url", type=source_url)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly permit configured model calls"
    )
    parser.add_argument(
        "--synthetic-sample", action="store_true", help="Use fixed fictional/scripted data"
    )
    args = parser.parse_args()
    if args.synthetic_sample:
        if args.live or args.slug or args.source_url:
            parser.error("synthetic sample cannot be combined with live or source inputs")
        slug = "synthetic-example"
    else:
        slug = args.slug or ""
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            parser.error("a valid --slug is required")
    try:
        target = output_path(args.out, slug)
    except ValueError as error:
        parser.error(str(error))  # Fixed path-policy strings, never page/provider input.
    try:
        if args.synthetic_sample:
            result, now = synthetic_result()
            supplied = True
        else:
            existing = [
                args.snapshots_dir / f"{slug}.{ext}"
                for ext in ("html", "pdf")
                if (args.snapshots_dir / f"{slug}.{ext}").is_file()
            ]
            if len(existing) != 1:
                parser.error("expected exactly one local .html or .pdf for the slug")
            path = existing[0]
            data = path.read_bytes()
            now = datetime.now(UTC)
            digest = hashlib.sha256(data).hexdigest()
            kind: Literal["html", "pdf"] = "html" if path.suffix == ".html" else "pdf"
            fetch = FetchResult(
                url=path.resolve().as_uri(),
                final_url=path.resolve().as_uri(),
                status="ok",
                content=data,
                content_sha256=digest,
                fetched_at=now.isoformat(),
                content_type="text/html" if kind == "html" else "application/pdf",
            )
            source = (
                SourceInfo(
                    url=args.source_url,
                    retrieved_on=now.date().isoformat(),
                    content_sha256=digest,
                    format=kind,
                    page_state="unknown",
                )
                if args.source_url
                else None
            )
            config = LLMConfig.from_env()
            if not args.live:
                config = config.model_copy(update={"cache_mode": "read_only"})
            client = build_client(config)
            try:
                result = run_pipeline(fetch, client, source=source)
            finally:
                client.close()
            supplied = args.source_url is not None
        rendered = render_report(result, now=now, source_url_is_user_supplied=supplied)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
    except (OSError, ValueError):
        print(
            "Report generation failed: check local input, configuration and output path.",
            file=sys.stderr,
        )
        return 1
    print(f"Report written; pipeline status: {result.status}")
    return 0 if result.status in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
