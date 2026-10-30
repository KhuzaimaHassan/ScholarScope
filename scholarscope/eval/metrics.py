"""Count normalized content decisions, NEVER infer absence from extraction failure.

Precision/recall score retained claims independently of evidence verification.
Presence checks use a small independent oracle, not another verifier invocation.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scholarscope.eval.loader import GoldLabel
from scholarscope.eval.normalize import canonical
from scholarscope.pipeline import PipelineResult
from scholarscope.schema import RequirementFields
from scholarscope.segmenter import SegmentedDocument

FIELD_GROUPS = {
    "program_name": "identity",
    "institution": "identity",
    "degree_levels": "identity",
    "application_link": "identity",
    "funding_coverage": "funding",
    "required_documents": "documents",
    "recommenders": "documents",
}
DEADLINE_DIMENSIONS = ("date", "type", "cycle_year", "time", "timezone", "rolling", "status")


@dataclass(frozen=True)
class ProgramEvaluation:
    gold: GoldLabel
    pipeline: PipelineResult
    document: SegmentedDocument
    layout: str
    elapsed_seconds: float


def quote_normalize(text: str) -> str:
    """Independent full-string presence oracle implementing ADR 012 formatting only."""
    text = re.sub(r"-\r?\n", "", text)
    text = text.translate({ord(c): None for c in "\u00ad\u200b\u200c\u200d\u2060\ufeff"})
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans("‘’“”–—", "''\"\"--"))
    return " ".join(text.split())


def _counts() -> dict[str, Any]:
    return {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "decisions": 0,
        "exact": 0,
        "excluded": 0,
        "excluded_gold_items": 0,
        "excluded_predicted_items": 0,
        "confusion": {},
    }


def _decision(gold: Any, pred: Any, name: str) -> tuple[bool, bool, bool]:
    expected, actual = gold.model_dump(mode="json"), pred.model_dump(mode="json")
    same = gold.status == pred.status
    if gold.status == "present":
        same = same and canonical(expected["value"], field=name) == canonical(
            actual["value"], field=name
        )
    elif gold.status == "in_linked_document":
        same = same and gold.linked_url == pred.linked_url
    return gold.status == "present", pred.status == "present", same


def _update(counts: dict[str, Any], gold: Any, pred: Any, name: str) -> bool:
    positive, predicted, same = _decision(gold, pred, name)
    counts["decisions"] += 1
    counts["exact"] += same
    counts["tp"] += positive and predicted and same
    counts["fp"] += predicted and not (positive and same)
    counts["fn"] += positive and not (predicted and same)
    key = f"{gold.status}->{pred.status}"
    counts["confusion"][key] = counts["confusion"].get(key, 0) + 1
    return same


def deadline_key(value: Any) -> str:
    data = value.model_dump(mode="json")
    return canonical({key: data[key] for key in DEADLINE_DIMENSIONS})


def condition_key(value: Any) -> str:
    data = value.model_dump(mode="json")
    return canonical({key: data[key] for key in ("kind", "value", "required", "applies_to")})


def _list_score(gold: list[Any], pred: list[Any], key: Any) -> dict[str, Any]:
    expected, actual = Counter(map(key, gold)), Counter(map(key, pred))
    counts = _counts()
    counts.update(
        tp=sum((expected & actual).values()),
        fp=sum((actual - expected).values()),
        fn=sum((expected - actual).values()),
        decisions=1,
        exact=int(expected == actual),
    )
    return counts


def owners(record: Any) -> list[tuple[str, Any]]:
    result = [
        (f"fields.{name}", getattr(record.fields, name))
        for name in sorted(RequirementFields.model_fields)
    ]
    result += [(f"deadlines[{i}]", value) for i, value in enumerate(record.deadlines)]
    result += [(f"conditions[{i}]", value) for i, value in enumerate(record.conditions)]
    return result


def _owner_name(path: str) -> str:
    return path.removeprefix("fields.").split("[", 1)[0]


def _presence(
    program: ProgramEvaluation,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    pipeline, doc = program.pipeline, program.document
    counts = {"checked": 0, "found": 0, "excluded": 0}
    bugs: list[dict[str, Any]] = []
    by_field: dict[str, Any] = {}
    reports = (
        {(item.owner_path, item.evidence_index): item for item in pipeline.verification.items}
        if pipeline.verification
        else {}
    )
    passages = {p.id: p for p in doc.passages}
    if pipeline.record is None:
        return counts, bugs, by_field
    for path, item in owners(pipeline.record):
        if item.verification != "verified":
            continue
        for i, evidence in enumerate(item.evidence):
            counts["checked"] += 1
            field = by_field.setdefault(
                _owner_name(path), {"checked": 0, "found": 0, "excluded": 0}
            )
            field["checked"] += 1
            check = reports.get((path, i))
            passage = passages.get(evidence.passage_id or "")
            valid = False
            if check and check.matched and passage:
                start, end = check.matched
                quote = quote_normalize(evidence.quote)
                valid = (
                    0 <= start < end <= len(doc.text)
                    and (passage.start <= start < passage.end or passage.start < end <= passage.end)
                    and len(quote) >= 6
                    and len(re.findall(r"[^\W_]+", quote)) >= 2
                    and "..." not in quote
                    and "…" not in quote
                    and check.quote == evidence.quote
                    and quote_normalize(doc.text[start:end]) == quote
                )
            counts["found"] += valid
            field["found"] += valid
            if not valid:
                bugs.append(
                    {
                        "slug": program.gold.slug,
                        "field": path,
                        "quote": evidence.quote,
                        "error": "VERIFIER BUG: verified quote lacks independent cited presence",
                    }
                )
    return counts, bugs, by_field


def score_program(program: ProgramEvaluation) -> dict[str, Any]:
    label, pipeline = program.gold, program.pipeline
    predicted, gold = pipeline.record, label.record
    extraction = pipeline.extraction
    failures = (
        list(extraction.failed_groups)
        if extraction
        else ["identity", "funding", "documents", "deadlines", "conditions"]
    )
    rejects = list(extraction.rejected_items) if extraction else []
    rejected_fields = {r.index for r in rejects if isinstance(r.index, str)}
    rejected_lists = {r.group for r in rejects if r.group in {"conditions", "deadlines"}}
    fields: dict[str, Any] = {}
    abstentions: dict[str, Any] = {
        "count": 0,
        "agrees": 0,
        "retained_value_correct": 0,
        "excluded": 0,
        "by_reason": {},
    }
    dangerous: list[dict[str, Any]] = []
    verified_comparable = 0
    verified_by_field: dict[str, int] = {}
    abstentions_by_field: dict[str, Any] = {}
    confidence: list[dict[str, Any]] = []

    def abstain(reason: str, agrees: bool, retained: bool, name: str) -> None:
        entry = abstentions["by_reason"].setdefault(
            reason, {"count": 0, "agrees": 0, "retained_value_correct": 0}
        )
        field = abstentions_by_field.setdefault(
            name, {"count": 0, "agrees": 0, "retained_value_correct": 0}
        )
        for counter in (abstentions, entry, field):
            counter["count"] += 1
            counter["agrees"] += agrees
            counter["retained_value_correct"] += retained

    def danger(path: str, item: Any, expected: Any) -> None:
        dangerous.append(
            {
                "slug": label.slug,
                "field": path,
                "predicted": item.model_dump(mode="json", exclude={"evidence"}),
                "gold": expected,
                "quote": [e.quote for e in item.evidence],
            }
        )

    for name, group in FIELD_GROUPS.items():
        counts = _counts()
        expected = getattr(gold.fields, name)
        if predicted is None or group in failures or name in rejected_fields:
            counts["excluded"] = 1
            abstentions["excluded"] += 1
        else:
            actual = getattr(predicted.fields, name)
            same = _update(counts, expected, actual, name)
            verified_comparable += actual.verification == "verified"
            verified_by_field[name] = int(actual.verification == "verified")
            if actual.verification == "verified" and not same:
                danger(f"fields.{name}", actual, expected.model_dump(mode="json"))
            reason = (
                "unverified"
                if actual.verification == "unverified"
                else actual.status
                if actual.status != "present"
                else "not_checked"
                if actual.verification == "not_checked"
                else None
            )
            if reason:
                agrees = (
                    expected.status != "present"
                    if reason in {"unverified", "not_checked"}
                    else actual.status == expected.status
                )
                abstain(reason, agrees, same, name)
            if actual.confidence is not None:
                confidence.append({"field": name, "confidence": actual.confidence, "correct": same})
        fields[name] = counts

    deadlines = _counts()
    conditions = _counts()
    set_status: dict[str, Any] = {"checked": 0, "matches": 0, "excluded": 0, "confusion": {}}
    list_cases: tuple[tuple[str, list[Any], dict[str, Any], Callable[[Any], str]], ...] = (
        ("deadlines", gold.deadlines, deadlines, deadline_key),
        ("conditions", gold.conditions, conditions, condition_key),
    )
    for group, expected, counts, key in list_cases:
        actual = getattr(predicted, group) if predicted else []
        excluded = predicted is None or group in failures or group in rejected_lists
        if excluded:
            # Rejection indices refer to provider output, not aligned gold indices.
            # Conservatively exclude the whole list; do not guess missing siblings.
            counts.update(
                excluded=1, excluded_gold_items=len(expected), excluded_predicted_items=len(actual)
            )
            abstentions["excluded"] += 1
        else:
            counts.update(_list_score(expected, actual, key))
        gold_keys = {key(value) for value in expected}
        for i, value in enumerate(actual):
            verified_comparable += value.verification == "verified"
            verified_by_field[group] = verified_by_field.get(group, 0) + int(
                value.verification == "verified"
            )
            if value.verification == "verified" and key(value) not in gold_keys:
                danger(f"{group}[{i}]", value, [v.model_dump(mode="json") for v in expected])
            if not excluded and value.verification != "verified":
                reason = f"{group}:{value.verification}"
                if group == "deadlines":
                    # No gold verification axis: withholding agrees only if gold
                    # has no present claim of this type/cycle, not merely a bad quote.
                    agrees = not any(
                        v.status == "present"
                        and v.type == value.type
                        and v.cycle_year == value.cycle_year
                        for v in expected
                    )
                else:
                    agrees = not any(v.kind == value.kind for v in expected)
                abstain(reason, agrees, key(value) in gold_keys, group)
            elif not excluded and group == "deadlines" and value.status == "ambiguous":
                abstain(
                    "deadlines:ambiguous",
                    any(
                        v.status == "ambiguous"
                        and v.type == value.type
                        and v.cycle_year == value.cycle_year
                        for v in expected
                    ),
                    key(value) in gold_keys,
                    group,
                )
        if group == "deadlines":
            if excluded:
                set_status["excluded"] = 1
            else:
                if predicted is None:
                    raise ValueError("a scored deadline set requires a prediction")
                set_status["checked"] = 1
                match = gold.deadlines_status == predicted.deadlines_status
                set_status["matches"] = int(match)
                set_status["confusion"][
                    f"{gold.deadlines_status}->{predicted.deadlines_status}"
                ] = 1
                counts["exact"] *= match
                if predicted.deadlines_status != "present":
                    abstain("deadline_set:" + predicted.deadlines_status, match, match, "deadlines")
    fields["conditions"] = conditions
    presence, bugs, presence_by_field = _presence(program)
    return {
        "slug": label.slug,
        "layout": program.layout,
        "status": pipeline.status,
        "source": gold.source.model_dump(mode="json"),
        "fields": {name: _finish(entry) for name, entry in fields.items()},
        "deadlines": _finish(deadlines),
        "deadline_set_status": {
            **set_status,
            "rate": _ratio(set_status["matches"], set_status["checked"]),
        },
        "evidence_presence": {**presence, "rate": _ratio(presence["found"], presence["checked"])},
        "evidence_by_field": presence_by_field,
        "verifier_bugs": bugs,
        "abstentions": abstentions,
        "abstentions_by_field": abstentions_by_field,
        "dangerous_errors": dangerous,
        "confidence_diagnostic": confidence,
        "verified_comparable_claims": verified_comparable,
        "verified_by_field": verified_by_field,
        "failed_groups": [
            {
                "slug": label.slug,
                "group": group,
                "status": next(
                    iter(
                        re.findall(
                            r"EXTRACTION_FAILED:" + re.escape(group) + r":(\w+)",
                            predicted.notes or "",
                        )
                    ),
                    "pipeline_unavailable",
                )
                if predicted
                else "pipeline_unavailable",
            }
            for group in failures
        ],
        # Do not echo raw rejected items: they can contain arbitrary page content/keys.
        "rejected_items": [
            {"slug": label.slug, "group": r.group, "index": r.index, "reason": r.reason}
            for r in rejects
        ],
        "latency_seconds": program.elapsed_seconds,
        "usage": extraction.usage.model_dump()
        if extraction
        else {"input_tokens": None, "output_tokens": None},
        "versions": pipeline.versions,
        "truncated": extraction.truncated if extraction else None,
        "passages_dropped": extraction.passages_dropped if extraction else None,
        "suspicious_passages": [
            {"passage_id": p.passage_id, "reasons": list(p.reasons)}
            for p in pipeline.suspicious_passages
        ],
    }


def _ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def _finish(counts: dict[str, Any]) -> dict[str, Any]:
    tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
    return {
        **counts,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "decision_accuracy": _ratio(counts["exact"], counts["decisions"]),
    }


def _sum_counts(entries: list[dict[str, Any]]) -> dict[str, Any]:
    total = _counts()
    for entry in entries:
        for key in total:
            if key == "confusion":
                for pair, count in entry[key].items():
                    total[key][pair] = total[key].get(pair, 0) + count
            else:
                total[key] += entry[key]
    return total


def aggregate(programs: list[dict[str, Any]]) -> dict[str, Any]:
    """Micro counts, with explicit denominators/exclusions and null for empty n."""
    import statistics

    names = (*FIELD_GROUPS, "conditions")
    per_field = {
        name: _finish(_sum_counts([p["fields"][name] for p in programs])) for name in names
    }
    field_total = _finish(_sum_counts([p["fields"][name] for p in programs for name in names]))
    deadlines = _finish(_sum_counts([p["deadlines"] for p in programs]))
    per_field["deadlines"] = dict(deadlines)
    confidence_pairs = [item for p in programs for item in p["confidence_diagnostic"]]
    for name, entry in per_field.items():
        presence: dict[str, Any] = {
            key: sum(p["evidence_by_field"].get(name, {}).get(key, 0) for p in programs)
            for key in ("checked", "found", "excluded")
        }
        presence["rate"] = _ratio(presence["found"], presence["checked"])
        entry["evidence_presence"] = presence
        abstention: dict[str, Any] = {
            key: sum(p["abstentions_by_field"].get(name, {}).get(key, 0) for p in programs)
            for key in ("count", "agrees", "retained_value_correct")
        }
        abstention.update(
            rate=_ratio(abstention["agrees"], abstention["count"]), excluded=entry["excluded"]
        )
        entry["abstentions"] = abstention
        errors = [
            e for p in programs for e in p["dangerous_errors"] if _owner_name(e["field"]) == name
        ]
        verified = sum(p["verified_by_field"].get(name, 0) for p in programs)
        entry["dangerous_errors"] = errors
        entry["dangerous_error_rate"] = {
            "errors": len(errors),
            "verified_claims": verified,
            "rate": _ratio(len(errors), verified),
            "excluded": entry["excluded"],
        }
        entry["confidence_diagnostic"] = _confidence(
            [p for p in confidence_pairs if p["field"] == name]
        )
    evidence = {
        key: sum(p["evidence_presence"][key] for p in programs)
        for key in ("checked", "found", "excluded")
    }
    evidence["rate"] = _ratio(evidence["found"], evidence["checked"])
    abstentions = {
        key: sum(p["abstentions"][key] for p in programs)
        for key in ("count", "agrees", "retained_value_correct", "excluded")
    }
    abstentions["rate"] = _ratio(abstentions["agrees"], abstentions["count"])
    reasons: dict[str, Any] = {}
    for program in programs:
        for reason, entry in program["abstentions"]["by_reason"].items():
            counter = reasons.setdefault(reason, {key: 0 for key in entry})
            for key, value in entry.items():
                counter[key] += value
    abstentions["by_reason"] = reasons
    sets = {
        key: sum(p["deadline_set_status"][key] for p in programs)
        for key in ("checked", "matches", "excluded")
    }
    sets["rate"] = _ratio(sets["matches"], sets["checked"])
    sets["confusion"] = dict(
        sum((Counter(p["deadline_set_status"]["confusion"]) for p in programs), Counter())
    )
    usage: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens"):
        values = [p["usage"][key] for p in programs if p["usage"][key] is not None]
        usage[key] = {
            "sum_known": sum(values),
            "median_known": statistics.median(values) if values else None,
            "known_programs": len(values),
            "unknown_programs": len(programs) - len(values),
        }
    verified_count = sum(p["verified_comparable_claims"] for p in programs)
    dangerous_count = sum(len(p["dangerous_errors"]) for p in programs)
    return {
        "programs": len(programs),
        "fields": field_total,
        "per_field": per_field,
        "deadlines": deadlines,
        "deadline_set_status": sets,
        "evidence_presence": evidence,
        "abstentions": abstentions,
        "usage": usage,
        "confidence_diagnostic": _confidence(confidence_pairs),
        "median_seconds": statistics.median(p["latency_seconds"] for p in programs)
        if programs
        else None,
        "failed_groups": [e for p in programs for e in p["failed_groups"]],
        "rejected_items": [e for p in programs for e in p["rejected_items"]],
        "verifier_bugs": [e for p in programs for e in p["verifier_bugs"]],
        "dangerous_error_rate": {
            "errors": dangerous_count,
            "verified_claims": verified_count,
            "rate": _ratio(dangerous_count, verified_count),
            "excluded": sum(p["fields"][n]["excluded"] for p in programs for n in FIELD_GROUPS),
        },
        "dangerous_errors": [e for p in programs for e in p["dangerous_errors"]],
    }


def _confidence(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Diagnostic only; never a threshold, verification decision or logic input."""
    import statistics

    confidence = [p["confidence"] for p in pairs]
    correct = [int(p["correct"]) for p in pairs]
    correlation = None
    if len(pairs) >= 2 and len(set(confidence)) > 1 and len(set(correct)) > 1:
        correlation = statistics.correlation(confidence, correct)
    return {
        "count": len(pairs),
        "mean_confidence": statistics.mean(confidence) if pairs else None,
        "accuracy": _ratio(sum(correct), len(pairs)),
        "pearson_correctness": correlation,
        "note": "advisory diagnostic only; no calibration or causal claim",
    }
