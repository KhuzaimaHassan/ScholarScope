"""Pure static HTML: untrusted text stays inert; provider messages are never rendered."""

from __future__ import annotations

import html
import json
import unicodedata
from datetime import UTC, datetime, tzinfo
from itertools import pairwise
from urllib.parse import urlsplit

from scholarscope.checklist import ItemKind, build_checklist
from scholarscope.deadlines import compare, resolve
from scholarscope.extraction.wire import GROUP_MODELS
from scholarscope.pipeline import PipelineResult
from scholarscope.schema import Evidence
from scholarscope.segmenter import Passage
from scholarscope.verifier import QuoteOutcome

DISPLAY_LIMIT = 2000  # Original characters per value/quote/note/version/passage.
SYNTHETIC_BANNER = (
    "SYNTHETIC EXAMPLE: fictional page and scripted extraction, not real data or a real model run"
)
_FOUND = {QuoteOutcome.EXACT, QuoteOutcome.NORMALIZED, QuoteOutcome.SPANS_PASSAGES}
_FIELD_GROUP = {
    "program_name": "identity",
    "institution": "identity",
    "degree_levels": "identity",
    "application_link": "identity",
    "funding_coverage": "funding",
    "required_documents": "documents",
    "recommenders": "documents",
}
_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #172d3d; background: #eef2f4; }
body { margin: 0; padding: 2rem 1rem; }
main { max-width: 76rem; margin: auto; background: white; padding: 2rem; border-radius: .6rem; }
header { border-bottom: .25rem solid #176d70; padding-bottom: 1rem; }
h1 { margin-bottom: .5rem; } h2 { margin-top: 2rem; color: #164d62; }
table { border-collapse: collapse; width: auto; } th, td { border: 1px solid #ccd6dd; padding: .65rem; text-align: left; vertical-align: top; }
th { background: #f0f5f7; } .table-scroll { overflow-x: auto; }
.value, blockquote, .source-text { white-space: pre-wrap; overflow-wrap: anywhere; unicode-bidi: plaintext; }
blockquote { border-left: .2rem solid #c2d6dd; margin: .7rem 0; padding-left: .7rem; }
.badge, .label { display: inline-block; padding: .2rem .45rem; border-radius: .25rem; background: #edf1f4; margin: .15rem; }
.verified { background: #d8f1e8; color: #14513d; } .unverified { background: #fde4e2; color: #7a2823; }
.failed, .banner { background: #fff0c6; color: #69430b; } .banner { padding: 1rem; font-weight: bold; }
.warning, .truncation { color: #843f11; } .passage { border-top: 1px solid #d4dde3; padding: 1rem 0; }
mark { background: #fff0a3; color: #172d3d; } .synthetic { text-decoration: underline dotted; }
small, footer { color: #465b6a; } footer { margin-top: 2rem; border-top: 1px solid #ccd6dd; padding-top: 1rem; }
a { color: #12577b; } li { margin: .6rem 0; }
"""


def _visible(text: str) -> str:
    # Bidi format controls must not reorder claims/badges. Offsets still use originals.
    return "".join(f"[U+{ord(c):04X}]" if unicodedata.category(c) == "Cf" else c for c in text)


def _string(value: object) -> str:
    if value is None:
        return "not stated"
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    )


def _escaped(text: str) -> str:
    return html.escape(_visible(text), quote=True)


def _display(value: object) -> str:
    text = _string(value)
    suffix = '… <span class="truncation">truncated</span>' if len(text) > DISPLAY_LIMIT else ""
    return _escaped(text[:DISPLAY_LIMIT]) + suffix


def safe_source_url(value: str) -> bool:
    """Only explicit HTTP(S) source links; credentials/control characters are refused."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
        )
    except ValueError:
        return False


def _badge(verification: str, failed: bool = False) -> str:
    if failed:
        return '<span class="badge failed">NOT EXTRACTED (group failed)</span>'
    label = {
        "verified": "quote found on page",
        "unverified": "quote NOT found: excluded from checklist",
    }.get(verification, "not_checked")
    css = verification if verification in {"verified", "unverified"} else "neutral"
    return f'<span class="badge {css}">{label}</span>'


def _source_passage(passage: Passage, spans: list[tuple[int, int]]) -> str:
    end = min(passage.end, passage.start + DISPLAY_LIMIT)
    synthetic = [(r.start, r.end) for r in passage.source_refs if getattr(r, "is_synthetic", False)]
    boundaries = {passage.start, end}
    for a, b in [*spans, *synthetic]:
        if a < end and b > passage.start:
            boundaries.update((max(a, passage.start), min(b, end)))
    points = sorted(boundaries)
    parts = []
    for a, b in pairwise(points):
        text = _escaped(passage.text[a - passage.start : b - passage.start])
        if any(x <= a and b <= y for x, y in synthetic):
            text = f'<span class="synthetic" data-start="{a}" data-end="{b}">{text}</span>'
        if any(x <= a and b <= y for x, y in spans):
            text = f'<mark data-start="{a}" data-end="{b}">{text}</mark>'
        parts.append(text)
    if passage.end > end:
        parts.append('… <span class="truncation">truncated</span>')
    return "".join(parts)


def render_report(
    pipeline_result: PipelineResult,
    *,
    now: datetime,
    reference_tz: tzinfo = UTC,
    source_url_is_user_supplied: bool,
) -> str:
    """Render explicit allowlists only; no clock, I/O, metrics, provider messages or raw rejects."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(reference_tz, tzinfo):
        raise TypeError("reference_tz must be a tzinfo")
    result, record = pipeline_result, pipeline_result.record
    extraction = result.extraction
    doc = result.document
    anchors = {p.id: f"passage-{i}" for i, p in enumerate(doc.passages)} if doc else {}
    found = result.verification.items if result.verification else ()
    failed = set(extraction.failed_groups) if extraction else set(GROUP_MODELS)

    def evidence(items: list[Evidence] | tuple[Evidence, ...], owner: str = "") -> str:
        parts = []
        for index, item in enumerate(items):
            ids = [item.passage_id] if item.passage_id else []
            for match in found:
                if match.owner_path == owner and match.evidence_index == index:
                    ids.extend(match.passage_ids)
            links = " ".join(
                f'<a href="#{anchors[pid]}">{_display(pid)}</a>'
                for pid in dict.fromkeys(ids)
                if pid in anchors
            )
            parts.append(
                f"<blockquote>{_display(item.quote)}<br>{links or 'passage unavailable'}</blockquote>"
            )
        return "".join(parts) or "No evidence quotes"

    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>ScholarScope evidence report</title><style>",
        _STYLE,
        "</style></head><body><main><header>",
    ]
    if result.versions.get("synthetic_example") is True:
        parts.append(f'<p class="banner">{SYNTHETIC_BANNER}</p>')
    title = (
        record.fields.program_name.value
        if record and record.fields.program_name.status == "present"
        else "not extracted"
    )
    parts.append(
        f"<h1>{_display(title)}</h1><p>Static evidence report · {_display(result.status)}</p>"
    )
    source = record.source.url if record else "not available"
    source_text = _display(source)
    if source_url_is_user_supplied and safe_source_url(source) and len(source) <= DISPLAY_LIMIT:
        source_text = (
            f'<a href="{_escaped(source)}" rel="noopener noreferrer nofollow">{source_text}</a>'
        )
    label = (
        "local read date"
        if source_url_is_user_supplied or source.startswith("file:")
        else "retrieved_on"
    )
    parts.append(
        f"<p>Source URL: {source_text}</p><p>{label}: {_display(record.source.retrieved_on if record else None)}</p>"
    )
    parts.append(
        "<p>verified means the quote appears on the page; it does not prove the value is right.</p></header>"
    )
    parts.append("<h2>Processing versions</h2><dl>")
    for key in (
        "cleaner",
        "pdf_extractor",
        "segmenter",
        "verifier",
        "prompts",
        "provider",
        "model",
    ):
        parts.append(f'<dt>{key}</dt><dd class="value">{_display(result.versions.get(key))}</dd>')
    parts.append(
        '</dl><h2>Extraction diagnostics</h2><div class="table-scroll"><table><thead><tr><th>Group</th><th>Status</th><th>Failure category</th></tr></thead><tbody>'
    )
    for group in GROUP_MODELS:
        detail = extraction.failure_details.get(group) if extraction else None
        status = extraction.group_status.get(group, "unavailable") if extraction else "unavailable"
        parts.append(
            f"<tr><th>{group}</th><td>{_display(status)} {_badge('not_checked', group in failed) if group in failed else ''}</td><td>{_display(detail.category if detail else None)}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    parts.append(f"<p>Failed groups: {_display(sorted(failed))}</p>")
    parts.append(
        f"<p>Input truncated: {_display(extraction.truncated if extraction else None)}; passages dropped: {_display(extraction.passages_dropped if extraction else None)}</p>"
    )
    parts.append('<ul class="rejections">')
    for rejected in extraction.rejected_items if extraction else ():
        parts.append(
            f"<li>{_display(rejected.group)} · {_display(rejected.index)} · {_display(rejected.reason)}</li>"
        )
    parts.append("</ul>")
    if record:
        parts.append(
            '<h2>Fields</h2><div class="table-scroll"><table><thead><tr><th>Field</th><th>Status</th><th>Verification</th><th>Value and notes</th><th>Evidence</th></tr></thead><tbody>'
        )
        for name in type(record.fields).model_fields:
            item = getattr(record.fields, name)
            data = item.model_dump(mode="json")
            status = "unknown (group failed)" if _FIELD_GROUP[name] in failed else item.status
            caution = (
                "<p>check the official page</p>"
                if item.status == "ambiguous"
                or item.verification != "verified"
                or _FIELD_GROUP[name] in failed
                else ""
            )
            parts.append(
                f'<tr><th>{name}</th><td><span class="badge">{_display(status)}</span></td><td>{_badge(item.verification, _FIELD_GROUP[name] in failed)}{caution}</td><td class="value">{_display(data["value"])}<p>Notes: {_display(item.notes)}</p><p>Linked URL (plain text): {_display(item.linked_url)}</p></td><td>{evidence(item.evidence, "fields." + name)}</td></tr>'
            )
        parts.append("</tbody></table></div>")
        checklist = build_checklist(record, now, reference_tz=reference_tz)
        parts.append("<h2>Deadlines</h2>")
        parts.append(_badge("not_checked", "deadlines" in failed) if "deadlines" in failed else "")
        deadlines_status = (
            "unknown (group failed)" if "deadlines" in failed else record.deadlines_status
        )
        parts.append(
            f'<p>Set status: {_display(deadlines_status)}</p><div class="table-scroll"><table><thead><tr><th>Label / type</th><th>Date / time / timezone</th><th>Verification / warnings</th><th>Evidence</th></tr></thead><tbody>'
        )
        for index, deadline in enumerate(record.deadlines):
            owner = f"deadlines[{index}]"
            warnings = sorted(
                {str(w) for c in checklist.items if c.source == owner for w in c.warnings}
            )
            caution = "check the official page" if not deadline.usable_for_logic else ""
            parts.append(
                f"<tr><td>{_display(deadline.label)}<br>{_display(deadline.type)}</td><td>{_display(deadline.date)}<br>{_display(deadline.time)}<br>{_display(deadline.timezone)}</td><td>{_badge(deadline.verification, 'deadlines' in failed)} {_display(caution)}<p>{_display(compare(deadline, now))}: {_display(resolve(deadline).reason)}</p><p>{_display(warnings)}</p><p>Notes: {_display(deadline.notes)}</p></td><td>{evidence(deadline.evidence, owner)}</td></tr>"
            )
        parts.append("</tbody></table></div><h2>Conditions</h2>")
        parts.append(
            _badge("not_checked", "conditions" in failed) if "conditions" in failed else ""
        )
        parts.append("<ul>")
        for index, condition in enumerate(record.conditions):
            data = condition.model_dump(mode="json")
            caution = "check the official page" if not condition.usable_for_logic else ""
            parts.append(
                f"<li><strong>{_display(condition.kind)}</strong> · {_display(data['value'])} · required: {_display(condition.required)} {_badge(condition.verification, 'conditions' in failed)} {_display(caution)}<p>Applies to: {_display(condition.applies_to)}; notes: {_display(condition.notes)}</p>{evidence(condition.evidence, f'conditions[{index}]')}</li>"
            )
        parts.append("</ul><h2>Checklist</h2>")
        parts.append(
            f"<p>Reference calendar: {_display(str(reference_tz))}; today: {_display(checklist.today.isoformat())}</p><ol>"
        )
        for item in checklist.items:
            caution = "check the official page" if item.kind == ItemKind.CHECK_OFFICIAL_PAGE else ""
            parts.append(
                f'<li data-checklist-id="{_escaped(item.id)}"><strong>{_display(item.title)}</strong> {_display(caution)}<p>Due date: {_display(item.due_date.isoformat() if item.due_date else None)}; warnings: {_display([str(w) for w in item.warnings])}</p><p>Policy: {_display(item.policy_id)} / {_display(item.policy_version)}; source: {_display(item.source)}</p>{evidence(item.evidence)}</li>'
            )
        parts.append(
            "</ol><p>Buffer policy: "
            + _display(checklist.policy.rationale)
            + " · "
            + _display(checklist.policy.source_note)
            + "</p>"
        )
        parts.append(f"<p>Record notes: {_display(record.notes)}</p>")
    else:
        parts.append("<p>Record not extracted. Check the official page.</p>")
    parts.append("<p>Profile eligibility is not part of this report.</p><h2>Source text</h2>")
    spans = [item.matched for item in found if item.outcome in _FOUND and item.matched is not None]
    flagged = {item.passage_id: item.reasons for item in result.suspicious_passages}
    for passage in doc.passages if doc else ():
        parts.append(
            f'<section class="passage" id="{anchors[passage.id]}"><h3>{_display(passage.id)}</h3><p>{_display(passage.locator)}</p>'
        )
        if passage.id in flagged:
            parts.append(
                '<p class="warning">flagged as suspicious (advisory): '
                + _display(list(flagged[passage.id]))
                + "</p>"
            )
        if any(getattr(ref, "is_synthetic", False) for ref in passage.source_refs):
            parts.append('<p class="label">link target added by the cleaner</p>')
        parts.append(
            '<div class="source-text">' + _source_passage(passage, spans) + "</div></section>"
        )
    if not doc or not doc.passages:
        parts.append("<p>No source passages available.</p>")
    parts.append(
        f"<footer><p>ScholarScope · generated {_display(now.isoformat())}</p><p>Generated locally from a snapshot. Not legal or admissions advice; always confirm on the official page.</p></footer></main></body></html>"
    )
    return "".join(parts)
