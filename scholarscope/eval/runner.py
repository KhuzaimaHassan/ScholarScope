"""Run the byte-to-record pipeline against local frozen gold inputs only."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from scholarscope.eval.loader import SkippedLabel, load_labels, local_input, optional_manifest
from scholarscope.eval.metrics import ProgramEvaluation
from scholarscope.llm.base import LLMClient
from scholarscope.pipeline import run_pipeline


def evaluate(
    client: LLMClient,
    *,
    gold_dir: Path,
    snapshots_dir: Path,
    manifest_path: Path,
    slugs: list[str] | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[list[ProgramEvaluation], list[SkippedLabel]]:
    labels, skipped = load_labels(gold_dir, slugs)
    manifest = optional_manifest(manifest_path)
    programs: list[ProgramEvaluation] = []
    for label in labels:
        try:
            fetch, document, layout = local_input(label, snapshots_dir, manifest=manifest)
        except (OSError, ValueError):
            skipped.append(
                SkippedLabel(label.slug, "missing/unreadable snapshot or frozen hash mismatch")
            )
            continue
        started = clock()
        result = run_pipeline(fetch, client, source=label.record.source)
        programs.append(
            ProgramEvaluation(label, result, document, layout, max(0, clock() - started))
        )
    return programs, skipped
