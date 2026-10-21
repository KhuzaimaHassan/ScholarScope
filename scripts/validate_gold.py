"""Validate gold label files against the schema and cross-field rules.

Usage:
    python scripts/validate_gold.py                       # all eval/gold/*.json (skips files starting with "_")
    python scripts/validate_gold.py eval/gold/foo.json    # specific files (underscore files allowed)

If eval/snapshots/<program_slug>.txt exists (page text saved by the labeler),
every evidence quote must appear in it after whitespace and quote-style
normalization. Snapshots are private and never committed (ADR 007).
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
# Preserve `python scripts/validate_gold.py` as a standalone repository command.
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
_deadline_schema = importlib.import_module("scholarscope.schema")
TZ_PATTERN = _deadline_schema.TZ_PATTERN
timezone_info = _deadline_schema.timezone_info

SCHEMA_PATH = ROOT / "eval" / "schema" / "gold-label.schema.json"
GOLD_DIR = ROOT / "eval" / "gold"
SNAPSHOT_DIR = ROOT / "eval" / "snapshots"

SMART_PUNCTUATION = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for src, dst in SMART_PUNCTUATION.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def check_evidence(
    where: str, status: str, value: Any, evidence: list[dict[str, Any]], errors: list[str]
) -> None:
    if status in ("present", "ambiguous") and not evidence:
        errors.append(f"{where}: status '{status}' needs at least one evidence quote")
    if status in ("absent", "in_linked_document") and evidence:
        errors.append(f"{where}: status '{status}' must have no evidence quotes")
    if status in ("absent", "in_linked_document", "ambiguous") and value is not None:
        errors.append(f"{where}: status '{status}' must have value null")
    if status == "present" and value in (None, "", []):
        errors.append(f"{where}: status 'present' needs a non-empty value")


def check_deadline(i: int, d: dict[str, Any], errors: list[str]) -> None:
    where = f"deadlines[{i}]"
    # Deadlines have no `value`; the field helper's ambiguous/null rule cannot apply.
    if d["status"] in ("present", "ambiguous") and not d["evidence"]:
        errors.append(f"{where}: status '{d['status']}' needs at least one evidence quote")
    if d["rolling"] and d["date"] is not None:
        errors.append(f"{where}: rolling deadline must have date null")
    if d["status"] == "present" and not d["rolling"] and d["date"] is None:
        errors.append(f"{where}: present, non-rolling deadline needs a date")
    if d["status"] == "ambiguous" and d["date"] is not None:
        errors.append(f"{where}: ambiguous deadline must have date null (put candidates in notes)")
    if d["time"] is not None and d["timezone"] is None:
        errors.append(f"{where}: time given, so timezone must be set (use 'unknown' if not stated)")
    if d["timezone"] is not None:
        try:
            timezone_info(d["timezone"])
        except ValueError:
            errors.append(f"{where}: timezone '{d['timezone']}' must be 'unknown', 'UTC+hh:mm', or an IANA name")
    if d["time"] is None and d["timezone"] is not None:
        errors.append(f"{where}: timezone set without a time; use null")


def check_condition(i: int, c: dict[str, Any], errors: list[str]) -> None:
    where = f"conditions[{i}]"
    if not c["evidence"]:
        errors.append(f"{where}: needs at least one evidence quote")
    value = c["value"]
    if c["kind"] == "min_gpa" and not (
        isinstance(value, dict) and isinstance(value.get("value"), (int, float)) and isinstance(value.get("scale"), (int, float))
    ):
        errors.append(f"{where}: min_gpa value must be {{value, scale}} as stated, not converted")
    if c["kind"] == "language" and not (
        isinstance(value, dict) and value.get("logic") in ("any", "all") and isinstance(value.get("options"), list) and value["options"]
    ):
        errors.append(f"{where}: language value must be {{logic: any|all, options: [...]}}")


def check_quotes_in_snapshot(label: dict[str, Any], errors: list[str]) -> str | None:
    snap = SNAPSHOT_DIR / f"{label['program_slug']}.txt"
    if not snap.exists():
        return f"note: no {snap.relative_to(ROOT)}; quote presence not checked"
    text = normalize(snap.read_text(encoding="utf-8", errors="replace"))
    quotes: list[tuple[str, str]] = []
    for name, f in label["fields"].items():
        quotes += [(f"fields.{name}", e["quote"]) for e in f["evidence"]]
    for i, d in enumerate(label["deadlines"]):
        quotes += [(f"deadlines[{i}]", e["quote"]) for e in d["evidence"]]
    for i, c in enumerate(label["conditions"]):
        quotes += [(f"conditions[{i}]", e["quote"]) for e in c["evidence"]]
    for where, q in quotes:
        if normalize(q) not in text:
            errors.append(f"{where}: quote not found in snapshot text: {q[:60]!r}")
    return None


def validate_file(path: Path, validator: Draft202012Validator) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    try:
        label = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"], notes
    label_notes = label.get("notes") if isinstance(label, dict) else None
    if isinstance(label_notes, str) and label_notes.startswith("SKELETON"):
        return ["skeleton, not labeled by hand"], notes
    for err in sorted(validator.iter_errors(label), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{loc}: {err.message}")
    if errors:
        return errors, notes
    if path.stem != label["program_slug"]:
        errors.append(f"file name '{path.stem}' must equal program_slug '{label['program_slug']}'")
    for key in ("retrieved_on",):
        try:
            date.fromisoformat(label["source"][key])
        except ValueError:
            errors.append(f"source.{key}: not a real calendar date")
    for name, f in label["fields"].items():
        check_evidence(f"fields.{name}", f["status"], f["value"], f["evidence"], errors)
        if f["status"] == "in_linked_document" and not f.get("linked_url"):
            errors.append(f"fields.{name}: in_linked_document needs linked_url")
    if label["deadlines_status"] == "present" and not label["deadlines"]:
        errors.append("deadlines_status 'present' needs at least one deadline")
    if label["deadlines_status"] != "present" and label["deadlines"] and label["deadlines_status"] != "ambiguous":
        errors.append(f"deadlines_status '{label['deadlines_status']}' must have an empty deadlines list")
    for i, d in enumerate(label["deadlines"]):
        check_deadline(i, d, errors)
    for i, c in enumerate(label["conditions"]):
        check_condition(i, c, errors)
    note = check_quotes_in_snapshot(label, errors)
    if note:
        notes.append(note)
    return errors, notes


def main(argv: list[str]) -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    if argv:
        files = [Path(a) for a in argv]
    else:
        files = sorted(p for p in GOLD_DIR.glob("*.json") if not p.name.startswith("_"))
    if not files:
        print("No gold label files found.")
        return 0
    failed = 0
    for path in files:
        errors, notes = validate_file(path, validator)
        status = "FAIL" if errors else "ok"
        print(f"{status}  {path}")
        for n in notes:
            print(f"      {n}")
        for e in errors:
            print(f"      - {e}")
        failed += bool(errors)
    print(f"\n{len(files) - failed}/{len(files)} files valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
