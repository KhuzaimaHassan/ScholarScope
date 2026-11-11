"""ADR 024: a parallel containment-only diagnostic; strict metrics stay untouched."""

from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from scholarscope.eval.metrics import (
    DEADLINE_DIMENSIONS,
    FIELD_GROUPS,
    ProgramEvaluation,
    _counts,
    _finish,
    _owner_name,
    _ratio,
    _sum_counts,
    quote_normalize,
    score_program,
)
from scholarscope.eval.normalize import canonical, normalize_value


@dataclass(frozen=True)
class IndexedItem:
    """Original index is identity; shuffling traversal does not reassign it."""

    index: int
    value: Any = field(repr=False)
    quotes: tuple[str, ...] = field(repr=False)
    verified: bool = False


@dataclass(frozen=True)
class EvidencePair:
    gold_index: int
    predicted_index: int
    exact_quote: bool
    overlap_length: int


def pair_items(gold: list[IndexedItem], predicted: list[IndexedItem]) -> tuple[EvidencePair, ...]:
    """Greedy exact/length/kind/gold-index/pred-index order, never token matching."""
    for items in (gold, predicted):
        if len({item.index for item in items}) != len(items):
            raise ValueError("pairing requires unique stable indices")
    candidates = []
    for g in gold:
        g_quotes = {q for raw in g.quotes if (q := quote_normalize(raw))}
        for p in predicted:
            p_quotes = {q for raw in p.quotes if (q := quote_normalize(raw))}
            overlaps = [
                (a == b, min(len(a), len(b)))
                for a in g_quotes
                for b in p_quotes
                if a in b or b in a
            ]
            if not overlaps:
                continue
            exact = any(equal for equal, _ in overlaps)
            length = max(length for _, length in overlaps)
            same_kind = getattr(g.value, "kind", None) == getattr(p.value, "kind", None)
            candidates.append((-int(exact), -length, -int(same_kind), g.index, p.index))
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    result = []
    for priority_exact, negative_length, _, gold_index, pred_index in sorted(candidates):
        if gold_index not in used_gold and pred_index not in used_pred:
            used_gold.add(gold_index)
            used_pred.add(pred_index)
            result.append(
                EvidencePair(gold_index, pred_index, bool(-priority_exact), -negative_length)
            )
    return tuple(sorted(result, key=lambda pair: (pair.gold_index, pair.predicted_index)))


def normalize_document(value: str) -> str:
    text = " ".join(value.casefold().split())
    return re.sub(r"^(?:a|an|the)\s+", "", text, count=1)


def _tree(value: Any, *, text: bool) -> Any:
    if isinstance(value, str):
        return value if text else None
    if isinstance(value, (bool, int, float)):
        return None if text else value
    if isinstance(value, dict):
        result = {
            key: child for key, v in value.items() if (child := _tree(v, text=text)) is not None
        }
        return result or None
    if isinstance(value, list):
        children = [child for v in value if (child := _tree(v, text=text)) is not None]
        return children or None
    return None


def structured(item: Any, family: str) -> dict[str, Any]:
    data = item.model_dump(mode="json")
    if family == "funding_coverage":
        return {
            key: data.get(key) for key in ("item", "amount", "amount_max", "currency", "period")
        }
    if family == "deadlines":
        return {key: data[key] for key in DEADLINE_DIMENSIONS}
    value = (
        data["value"]
        if data["kind"] in {"min_gpa", "language"}
        else _tree(data["value"], text=False)
    )
    return {
        "kind": data["kind"],
        "required": data["required"],
        "value": value,
        "applies_to_presence": bool(" ".join((data.get("applies_to") or "").split())),
    }


def text_projection(item: Any, family: str) -> dict[str, Any]:
    data = item.model_dump(mode="json")
    result = {key: data.get(key) for key in ("note", "notes", "label", "applies_to")}
    if family == "conditions" and data["kind"] not in {"min_gpa", "language"}:
        result["value"] = _tree(data["value"], text=True)
    return normalize_value(result)


def _differences(gold: dict[str, Any], predicted: dict[str, Any]) -> list[dict[str, Any]]:
    g, p = normalize_value(gold), normalize_value(predicted)
    return [
        {"field": key, "gold": g.get(key), "predicted": p.get(key)}
        for key in sorted(g.keys() | p.keys())
        if canonical(g.get(key)) != canonical(p.get(key))
    ]


def _advisory() -> dict[str, int]:
    return {"compared": 0, "equal": 0, "different": 0}


def _indexed(
    values: list[Any], *, evidence: list[Any] | None = None, verified: bool = False
) -> list[IndexedItem]:
    return [
        IndexedItem(
            i,
            value,
            tuple(e.quote for e in (evidence if evidence is not None else value.evidence)),
            verified if evidence is not None else value.verification == "verified",
        )
        for i, value in enumerate(values)
    ]


def _collection(
    family: str,
    gold: list[IndexedItem],
    predicted: list[IndexedItem],
    *,
    slug: str,
    excluded: bool,
    audit_retained: bool = True,
    status_equal: bool = True,
) -> dict[str, Any]:
    pairs = pair_items(gold, predicted)
    g_items, p_items = {g.index: g for g in gold}, {p.index: p for p in predicted}
    paired_pred = {pair.predicted_index: pair.gold_index for pair in pairs}
    counts, advisory = _counts(), _advisory()
    errors, matches = [], []
    correct = 0
    for pair in pairs:
        g, p = g_items[pair.gold_index], p_items[pair.predicted_index]
        differences = _differences(structured(g.value, family), structured(p.value, family))
        correct += not differences
        g_text, p_text = text_projection(g.value, family), text_projection(p.value, family)
        text_equal = canonical(g_text) == canonical(p_text)
        if not excluded and (g_text or p_text):
            advisory["compared"] += 1
            advisory["equal"] += text_equal
            advisory["different"] += not text_equal
        matches.append(
            {
                **asdict(pair),
                "structured_agreement": not differences,
                "advisory_text_agreement": text_equal
                if not excluded and (g_text or p_text)
                else None,
            }
        )
    if excluded:
        counts.update(
            excluded=1, excluded_gold_items=len(gold), excluded_predicted_items=len(predicted)
        )
    else:
        counts.update(
            tp=correct,
            fp=len(predicted) - correct,
            fn=len(gold) - correct,
            decisions=1,
            exact=int(correct == len(gold) == len(predicted) and status_equal),
        )
    for p in sorted(predicted, key=lambda item: item.index):
        if not p.verified or not audit_retained:
            continue
        matched_gold = g_items.get(paired_pred.get(p.index, -1))
        differences = (
            _differences(structured(matched_gold.value, family), structured(p.value, family))
            if matched_gold
            else []
        )
        if matched_gold is None or differences:
            path = f"fields.{family}" if family == "funding_coverage" else family
            errors.append(
                {
                    "slug": slug,
                    "field": f"{path}[{p.index}]",
                    "predicted_index": p.index,
                    "gold_index": matched_gold.index if matched_gold else None,
                    "reason": "unpaired_prediction"
                    if matched_gold is None
                    else "structured_disagreement",
                    "disagreements": differences,
                    "predicted": structured(p.value, family),
                    "gold": structured(matched_gold.value, family) if matched_gold else None,
                }
            )
    return {
        "counts": _finish(counts),
        "pairs": matches,
        "dangerous_errors": errors,
        "verified": sum(p.verified for p in predicted) if audit_retained else 0,
        "advisory_text_agreement": advisory,
    }


def score_evidence_matched(
    program: ProgramEvaluation, strict: dict[str, Any] | None = None
) -> dict[str, Any]:
    baseline = strict if strict is not None else score_program(program)
    record, gold = program.pipeline.record, program.gold.record
    fields = deepcopy(baseline["fields"])
    errors = [
        deepcopy(e)
        for e in baseline["dangerous_errors"]
        if _owner_name(e["field"]) in FIELD_GROUPS
        and _owner_name(e["field"]) not in {"funding_coverage", "required_documents"}
    ]
    verified = {key: baseline["verified_by_field"].get(key, 0) for key in FIELD_GROUPS}
    pairings, advisory = {}, {}
    for family in ("conditions", "funding_coverage", "deadlines"):
        field_name = "deadlines" if family == "deadlines" else family
        source_counts = (
            baseline["deadlines"] if family == "deadlines" else baseline["fields"][family]
        )
        excluded = bool(source_counts["excluded"])
        status_equal = True
        if family == "funding_coverage":
            g_field = gold.fields.funding_coverage
            p_field = record.fields.funding_coverage if record else None
            g_values = g_field.value or []
            p_values = p_field.value or [] if p_field else []
            gs = _indexed(g_values, evidence=g_field.evidence)
            ps = (
                _indexed(
                    p_values, evidence=p_field.evidence, verified=p_field.verification == "verified"
                )
                if p_field
                else []
            )
            status_equal = p_field is not None and p_field.status == g_field.status
        else:
            gs = _indexed(getattr(gold, family))
            ps = _indexed(getattr(record, family)) if record else []
            if family == "deadlines":
                status_equal = (
                    record is not None and record.deadlines_status == gold.deadlines_status
                )
        scored = _collection(
            family,
            gs,
            ps,
            slug=program.gold.slug,
            excluded=excluded,
            audit_retained=not excluded or family != "funding_coverage",
            status_equal=status_equal,
        )
        if family == "funding_coverage":
            scored["counts"]["confusion"] = deepcopy(source_counts["confusion"])
        if family != "deadlines":
            fields[family] = scored["counts"]
        else:
            deadlines = scored["counts"]
        verified[field_name] = scored["verified"]
        errors.extend(scored["dangerous_errors"])
        pairings[family], advisory[family] = scored["pairs"], scored["advisory_text_agreement"]
    if record:
        for name in FIELD_GROUPS:
            if fields[name]["excluded"]:
                continue
            g_notes = getattr(gold.fields, name).notes
            p_notes = getattr(record.fields, name).notes
            if g_notes is not None or p_notes is not None:
                comparison = advisory.setdefault(name, _advisory())
                equal = canonical({"notes": g_notes}) == canonical({"notes": p_notes})
                comparison["compared"] += 1
                comparison["equal"] += equal
                comparison["different"] += not equal
    if record and not fields["required_documents"]["excluded"]:
        g, p = gold.fields.required_documents, record.fields.required_documents
        same = g.status == p.status
        if g.status == "present":
            same = same and Counter(map(normalize_document, g.value or [])) == Counter(
                map(normalize_document, p.value or [])
            )
        elif g.status == "in_linked_document":
            same = same and g.linked_url == p.linked_url
        counts = _counts()
        positive, actual = g.status == "present", p.status == "present"
        counts.update(
            tp=int(positive and actual and same),
            fp=int(actual and not (positive and same)),
            fn=int(positive and not (actual and same)),
            decisions=1,
            exact=int(same),
            confusion={f"{g.status}->{p.status}": 1},
        )
        fields["required_documents"] = _finish(counts)
        if p.verification == "verified" and not same:
            errors.append(
                {
                    "slug": program.gold.slug,
                    "field": "fields.required_documents",
                    "reason": "structured_disagreement",
                    "disagreements": [
                        {"field": "documents", "gold": g.value, "predicted": p.value}
                    ],
                }
            )
    return {
        "slug": program.gold.slug,
        "layout": program.layout,
        "fields": fields,
        "deadlines": deadlines,
        "deadline_set_status": deepcopy(baseline["deadline_set_status"]),
        "pairings": pairings,
        "advisory_text_agreement": advisory,
        "dangerous_errors": sorted(errors, key=lambda e: e["field"]),
        "verified_by_field": verified,
        "failed_groups": deepcopy(baseline["failed_groups"]),
        "rejected_items": deepcopy(baseline["rejected_items"]),
    }


def aggregate_evidence_matched(programs: list[dict[str, Any]]) -> dict[str, Any]:
    names = (*FIELD_GROUPS, "conditions", "deadlines")
    per_field = {}
    for name in names:
        counts = _finish(
            _sum_counts(
                [p["deadlines"] if name == "deadlines" else p["fields"][name] for p in programs]
            )
        )
        errors = [
            e for p in programs for e in p["dangerous_errors"] if _owner_name(e["field"]) == name
        ]
        kind = [e for e in errors if any(d["field"] == "kind" for d in e.get("disagreements", []))]
        other = [
            e
            for e in errors
            if e.get("reason") != "unpaired_prediction"
            and (
                not e.get("disagreements") or any(d["field"] != "kind" for d in e["disagreements"])
            )
        ]
        text = {
            key: sum(p["advisory_text_agreement"].get(name, {}).get(key, 0) for p in programs)
            for key in _advisory()
        }
        text["rate"] = _ratio(text["equal"], text["compared"])
        verified = sum(p["verified_by_field"].get(name, 0) for p in programs)
        per_field[name] = {
            **counts,
            "dangerous_errors": errors,
            "kind_disagreements": kind,
            "other_structured_disagreements": other,
            "unpaired_verified_items": [
                e for e in errors if e.get("reason") == "unpaired_prediction"
            ],
            "error_counts": {
                "total": len(errors),
                "kind_disagreements": len(kind),
                "other_structured_disagreements": len(other),
                "unpaired_verified": sum(e.get("reason") == "unpaired_prediction" for e in errors),
            },
            "advisory_text_agreement": text,
            "dangerous_error_rate": {
                "errors": len(errors),
                "verified_claims": verified,
                "rate": _ratio(len(errors), verified),
            },
        }
    result: dict[str, Any] = {
        "programs": len(programs),
        "per_field": per_field,
        "fields": _finish(
            _sum_counts(
                [p["fields"][name] for p in programs for name in (*FIELD_GROUPS, "conditions")]
            )
        ),
        "deadlines": _finish(_sum_counts([p["deadlines"] for p in programs])),
    }
    for key in (
        "dangerous_errors",
        "kind_disagreements",
        "other_structured_disagreements",
        "unpaired_verified_items",
    ):
        result[key] = [entry for name in names for entry in per_field[name][key]]
    text = {
        key: sum(per_field[name]["advisory_text_agreement"][key] for name in names)
        for key in _advisory()
    }
    result["advisory_text_agreement"] = {**text, "rate": _ratio(text["equal"], text["compared"])}
    result["failed_groups"] = [e for p in programs for e in p["failed_groups"]]
    result["rejected_items"] = [e for p in programs for e in p["rejected_items"]]
    result["error_counts"] = {
        key: sum(per_field[name]["error_counts"][key] for name in names)
        for key in (
            "total",
            "kind_disagreements",
            "other_structured_disagreements",
            "unpaired_verified",
        )
    }
    verified = sum(sum(p["verified_by_field"].values()) for p in programs)
    result["dangerous_error_rate"] = {
        "errors": len(result["dangerous_errors"]),
        "verified_claims": verified,
        "rate": _ratio(len(result["dangerous_errors"]), verified),
    }
    return result
