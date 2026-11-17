"""Private item diagnostics derived after scoring; never alter counts or pairs."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from scholarscope.eval.metrics import (
    ProgramEvaluation,
    condition_key,
    deadline_key,
    quote_normalize,
)
from scholarscope.eval.normalize import canonical

FAMILIES = ("conditions", "funding_coverage", "deadlines")


def _funding_key(item: Any) -> str:
    # Strict funding compares the complete value, including each item's note.
    return canonical(item.model_dump(mode="json"))


def _difference(
    gold: list[Any], predicted: list[Any], key: Callable[[Any], str]
) -> tuple[list[int], list[int]]:
    """Multiset subtraction; identical duplicates consume ascending indices."""
    remaining: dict[str, deque[int]] = defaultdict(deque)
    for index, item in enumerate(predicted):
        remaining[key(item)].append(index)
    missed = []
    for index, item in enumerate(gold):
        candidates = remaining[key(item)]
        if candidates:
            candidates.popleft()
        else:
            missed.append(index)
    return missed, sorted(index for indices in remaining.values() for index in indices)


def _entry(
    index: int,
    item: Any,
    owner: Any,
    category: str,
    *,
    is_gold: bool,
    reason: str,
    paired: int | None,
) -> dict[str, Any]:
    data = {
        "index": index,
        category: getattr(item, category),
        "evidence": [
            {"quote": quote_normalize(e.quote), "locator": e.locator} for e in owner.evidence
        ],
        "reason": reason,
        "paired_index": paired,
    }
    if not is_gold:
        data["verification"] = owner.verification
    return data


def item_diagnostics(
    program: ProgramEvaluation, strict: dict[str, Any], matched: dict[str, Any] | None = None
) -> dict[str, Any]:
    """List scored misses only; excluded families have empty, flagged lists.

    Funding entries inherit their field's evidence and verification. Every quote
    is normalized by the existing presence oracle; all locators are retained.
    Evidence-matched results consume existing pairings without recomputing them.
    """
    result = {}
    gold, predicted = program.gold.record, program.pipeline.record
    keys = {
        "conditions": condition_key,
        "funding_coverage": _funding_key,
        "deadlines": deadline_key,
    }
    for family in FAMILIES:
        counts = strict["deadlines"] if family == "deadlines" else strict["fields"][family]
        diagnostics: dict[str, Any] = {
            "excluded": bool(counts["excluded"]),
            "missed_gold_items": [],
            "unmatched_predicted_items": [],
        }
        result[family] = diagnostics
        if diagnostics["excluded"]:
            continue
        if predicted is None:
            raise ValueError("a scored item family requires a prediction")
        g_field, p_field = gold.fields.funding_coverage, predicted.fields.funding_coverage
        gs = (g_field.value or []) if family == "funding_coverage" else getattr(gold, family)
        ps = (p_field.value or []) if family == "funding_coverage" else getattr(predicted, family)

        gold_misses: list[tuple[int, str, int | None]] = []
        pred_misses: list[tuple[int, str, int | None]] = []
        if matched is None:
            missed, unmatched = _difference(gs, ps, keys[family])
            gold_misses = [(i, "multiset_difference", None) for i in missed]
            pred_misses = [(i, "multiset_difference", None) for i in unmatched]
        else:
            pairs = matched["pairings"][family]
            by_gold = {p["gold_index"]: p for p in pairs}
            by_pred = {p["predicted_index"]: p for p in pairs}
            for items, lookup, destination, counterpart in (
                (gs, by_gold, gold_misses, "predicted_index"),
                (ps, by_pred, pred_misses, "gold_index"),
            ):
                for index in range(len(items)):
                    pair = lookup.get(index)
                    if pair is not None and pair["structured_agreement"]:
                        continue
                    destination.append(
                        (
                            index,
                            "no_pair" if pair is None else "structured_disagreement",
                            None if pair is None else pair[counterpart],
                        )
                    )
        category = {"conditions": "kind", "funding_coverage": "item", "deadlines": "type"}[family]
        for items, field, is_gold, misses, key in (
            (gs, g_field, True, gold_misses, "missed_gold_items"),
            (ps, p_field, False, pred_misses, "unmatched_predicted_items"),
        ):
            diagnostics[key] = [
                _entry(
                    index,
                    items[index],
                    field if family == "funding_coverage" else items[index],
                    category,
                    is_gold=is_gold,
                    reason=reason,
                    paired=paired,
                )
                for index, reason, paired in misses
            ]
    return result
