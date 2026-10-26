"""Reject invalid claims explicitly, retaining valid siblings and rejected input."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from scholarscope.schema import Condition, Deadline, RequirementFields, RequirementRecord


@dataclass(frozen=True)
class RejectedItem:
    group: str
    index: int | str
    reason: str
    raw_item: Any


def absent(notes: str | None = None) -> dict[str, Any]:
    return {"status": "absent", "value": None, "evidence": [], "notes": notes}


def _unchecked(raw: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(raw)
    # Ignore claimed verifier state; do not carry arbitrary provider keys into
    # canonical models. All other constraints are enforced, never repaired.
    result["verification"] = "not_checked"
    return result


def _reason(error: ValidationError) -> str:
    # Do not echo entire model outputs into exception strings; raw_item is explicit.
    return "; ".join(
        f"{'.'.join(map(str, e['loc'])) or 'item'}: {e['msg']}"
        for e in error.errors(include_input=False, include_url=False)
    )


def convert_group(
    group: str,
    data: dict[str, Any],
    record_data: dict[str, Any],
    *,
    original: dict[str, Any] | None = None,
) -> list[RejectedItem]:
    """Populate a draft record, with no implicit claim of quote presence.

    List members are validated individually. Duplicate deadlines are rejected at
    their original index, rather than losing the entire group or repairing them.
    ``data`` is the parsed wire model dump: extra provider keys were ignored.
    """
    rejected: list[RejectedItem] = []
    original = data if original is None else original

    def raw_item(index: int | str) -> Any:
        if isinstance(index, int):
            raw_items = original.get(group, [])
            if isinstance(raw_items, list) and index < len(raw_items):
                return deepcopy(raw_items[index])
            return deepcopy(data[group][index])
        return deepcopy(original.get(index, data.get(index)))

    if group in {"identity", "funding", "documents"}:
        for name, raw in data.items():
            annotation = RequirementFields.model_fields[name].annotation
            if annotation is None:
                raise ValueError("canonical field must define a type annotation")
            try:
                value: Any = TypeAdapter(annotation).validate_python(_unchecked(raw))
            except ValidationError as error:
                rejected.append(RejectedItem(group, name, _reason(error), raw_item(name)))
                record_data["fields"][name] = absent(f"EXTRACTION_REJECTED:{group}:{name}")
            else:
                record_data["fields"][name] = value.model_dump()
        return rejected

    items = data[group]
    accepted: list[Any] = []
    adapter: TypeAdapter[Any] = TypeAdapter(Deadline if group == "deadlines" else Condition)
    for index, raw in enumerate(items):
        try:
            value = adapter.validate_python(_unchecked(raw))
            if group == "deadlines":
                # Enforce the Record's cross-item duplicate rule at each insertion.
                RequirementRecord.model_validate({**record_data, "deadlines": [*accepted, value]})
        except ValidationError as error:
            rejected.append(RejectedItem(group, index, _reason(error), raw_item(index)))
        else:
            accepted.append(value)
    record_data[group] = accepted
    if group == "deadlines":
        status = data["deadlines_status"]
        if status in {"absent", "in_linked_document"} and items:
            # This inconsistency is a set-level failure, not an empty successful set.
            rejected.append(
                RejectedItem(group, "set", "non-present set has entries", deepcopy(data))
            )
            record_data["deadlines"] = []
            status = "absent"
        if status == "in_linked_document" and not (data["linked_url"] or "").strip():
            rejected.append(
                RejectedItem(group, "set", "linked set needs linked_url", deepcopy(data))
            )
            status = "absent"
        if status == "present" and not accepted:
            if not rejected:
                rejected.append(
                    RejectedItem(group, "set", "present set has no entries", deepcopy(data))
                )
            status = "absent"
        record_data["deadlines_status"] = status
        # The canonical Record has no set-level linked_url/notes. Retain them
        # explicitly as metadata in record.notes, not as a fabricated Deadline.
        record_data["notes"] = (
            "\n".join(
                part for part in [record_data["notes"], data["notes"], data["linked_url"]] if part
            )
            or None
        )
    return rejected
