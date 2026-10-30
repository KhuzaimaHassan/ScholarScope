"""Evaluate frozen local snapshots. Offline/read-only cache unless --live is explicit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scholarscope.eval.loader import ROOT
from scholarscope.eval.report import build_report, write_report
from scholarscope.eval.runner import evaluate
from scholarscope.llm.config import LLMConfig, build_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--slugs", help="comma-separated labeled slugs")
    selection.add_argument("--all-labeled", action="store_true")
    parser.add_argument(
        "--live", action="store_true", help="allow configured LLM inference (never page fetching)"
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".cache/llm")
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "eval/gold")
    parser.add_argument("--snapshots-dir", type=Path, default=ROOT / "eval/snapshots")
    parser.add_argument("--manifest", type=Path, default=ROOT / "eval/manifest.json")
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args(argv)
    date = datetime.now(UTC).date().isoformat()
    out = args.out or ROOT / f"eval/reports/{date}.json"
    slugs = [s.strip() for s in args.slugs.split(",")] if args.slugs is not None else None
    if slugs is not None and any(not s for s in slugs):
        parser.error("--slugs must contain nonempty comma-separated slugs")
    try:
        config = LLMConfig.from_env()
        if not args.live:
            # Mandatory even if environment requests off/read_write; a missing
            # directory is an empty cache, never permission to call a provider.
            config = config.model_copy(update={"cache_mode": "read_only"})
        client = build_client(config, cache_dir=args.cache_dir)
        try:
            programs, skipped = evaluate(
                client,
                gold_dir=args.gold_dir,
                snapshots_dir=args.snapshots_dir,
                manifest_path=args.manifest,
                slugs=slugs,
            )
        finally:
            client.close()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        report = build_report(
            programs,
            skipped,
            date=date,
            git_commit=commit,
            seed=args.seed,
            mode="live" if args.live else "read_only",
            cache_exists=args.cache_dir.is_dir(),
        )
        report["configured_model"] = config.model
        report["configured_provider"] = config.provider
        report["git_dirty"] = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        write_report(
            report,
            programs,
            out,
            protected_dirs=(args.gold_dir, args.snapshots_dir, args.cache_dir),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        print(
            "Evaluation script error: check local inputs, output path and configuration.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Labels used: {len(programs)}; skipped: {len(skipped)}; "
        f"failed groups: {len(report['overall']['failed_groups'])}; "
        f"verifier bugs: {len(report['overall']['verifier_bugs'])}"
    )
    print(
        "Wrote JSON, Markdown and audit CSV. Reports are private/ignored; review before publishing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
