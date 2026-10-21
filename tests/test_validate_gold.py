"""Tests for scripts/validate_gold.py using the fictional example label."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("validate_gold", ROOT / "scripts" / "validate_gold.py")
assert spec is not None and spec.loader is not None
validate_gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_gold)

EXAMPLE = ROOT / "eval" / "gold" / "_example-fictional.json"


def _validator() -> Any:
    from jsonschema import Draft202012Validator

    schema = json.loads(validate_gold.SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _errors_for(label: dict[str, Any], tmp_path: Path) -> list[str]:
    path = tmp_path / f"{label['program_slug']}.json"
    path.write_text(json.dumps(label), encoding="utf-8")
    errors, _ = validate_gold.validate_file(path, _validator())
    return list(errors)


def _base() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_is_valid(tmp_path: Path) -> None:
    assert _errors_for(_base(), tmp_path) == []


def ambiguous_example() -> dict[str, Any]:
    """A fresh fictional copy; the committed example and real labels stay untouched."""
    label = copy.deepcopy(_base())
    label["deadlines"].append({
        "label": "Conflicting fictional scholarship notice", "type": "scholarship",
        "cycle_year": 2027, "date": None, "time": None, "timezone": None,
        "rolling": False, "status": "ambiguous",
        "evidence": [{"quote": "Fictional closing date: 20 January 2027"},
                     {"quote": "Fictional closing date: 21 January 2027"}],
        "notes": "Candidates: 2027-01-20 and 2027-01-21; neither selected.",
    })
    return label


def test_ambiguous_deadline_is_valid(tmp_path: Path) -> None:
    assert _errors_for(ambiguous_example(), tmp_path) == []


def test_ambiguous_deadline_with_date_is_rejected(tmp_path: Path) -> None:
    label = ambiguous_example()
    label["deadlines"][-1]["date"] = "2027-01-20"
    errors = _errors_for(label, tmp_path)
    assert any("ambiguous deadline must have date null" in e for e in errors)


def test_ambiguous_deadline_without_evidence_is_rejected(tmp_path: Path) -> None:
    label = ambiguous_example()
    label["deadlines"][-1]["evidence"] = []
    errors = _errors_for(label, tmp_path)
    assert any("status 'ambiguous' needs at least one evidence quote" in e for e in errors)


@pytest.mark.parametrize("notes", ["SKELETON", "SKELETON: not yet labeled by hand."])
def test_skeleton_notes_are_rejected(notes: str, tmp_path: Path) -> None:
    label = _base()
    label["notes"] = notes
    assert _errors_for(label, tmp_path) == ["skeleton, not labeled by hand"]


def test_skeleton_cli_exits_with_failure(tmp_path: Path) -> None:
    label = _base()
    label["notes"] = "SKELETON: not yet labeled by hand."
    path = tmp_path / f"{label['program_slug']}.json"
    path.write_text(json.dumps(label), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_gold.py"), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "skeleton, not labeled by hand" in result.stdout


def _absent_with_value(d: dict[str, Any]) -> None:
    d["fields"]["recommenders"]["value"] = {"count_min": 2}


def _time_without_timezone(d: dict[str, Any]) -> None:
    d["deadlines"][0]["timezone"] = None


def _gpa_without_scale(d: dict[str, Any]) -> None:
    d["conditions"][0]["value"] = 3.5


def _linked_without_url(d: dict[str, Any]) -> None:
    d["fields"]["required_documents"]["linked_url"] = None


def _rolling_with_date(d: dict[str, Any]) -> None:
    d["deadlines"][0]["rolling"] = True


def _present_without_quote(d: dict[str, Any]) -> None:
    d["fields"]["program_name"]["evidence"] = []


def _bad_hash(d: dict[str, Any]) -> None:
    d["source"]["content_sha256"] = "abc"


def _bad_language_shape(d: dict[str, Any]) -> None:
    d["conditions"][1]["value"] = {"options": []}


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_absent_with_value, "must have value null"),
        (_time_without_timezone, "timezone must be set"),
        (_gpa_without_scale, "min_gpa value must be"),
        (_linked_without_url, "needs linked_url"),
        (_rolling_with_date, "rolling deadline must have date null"),
        (_present_without_quote, "needs at least one evidence quote"),
        (_bad_hash, "content_sha256"),
        (_bad_language_shape, "language value must be"),
    ],
)
def test_invalid_labels_are_rejected(
    mutate: Callable[[dict[str, Any]], None], expected: str, tmp_path: Path
) -> None:
    label = copy.deepcopy(_base())
    mutate(label)
    errors = _errors_for(label, tmp_path)
    assert any(expected in e for e in errors), errors


def test_missing_quote_in_snapshot_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validate_gold, "SNAPSHOT_DIR", tmp_path)
    (tmp_path / "_example-fictional.txt").write_text(
        "Example Excellence Scholarship 2027-2028", encoding="utf-8"
    )
    errors = _errors_for(_base(), tmp_path)
    assert any("quote not found in snapshot text" in e for e in errors)
    assert not any("program_name" in e for e in errors)
