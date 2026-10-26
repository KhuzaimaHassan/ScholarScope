"""Local bytes -> extraction -> ALWAYS deterministic evidence verification.

No fetching, snapshot writes, or label access. Only the injected LLM client may
perform inference; tests inject FakeClient and prohibit real socket connections.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from scholarscope.cleaner import CLEANER_VERSION, CleanedHTML, clean_html
from scholarscope.extraction import PROMPT_VERSIONS, ExtractionResult, extract_record
from scholarscope.fetcher import FetchResult
from scholarscope.llm.base import LLMClient
from scholarscope.pdf_text import PDF_EXTRACTOR_VERSION, ExtractedPDF, extract_pdf_text
from scholarscope.schema import RequirementRecord, Source
from scholarscope.segmenter import SEGMENTER_VERSION, segment
from scholarscope.verifier import VERIFIER_VERSION, VerificationReport, verify_record


@dataclass(frozen=True)
class PipelineResult:
    status: str
    record: RequirementRecord | None
    extraction: ExtractionResult | None
    verification: VerificationReport | None
    versions: dict[str, object]
    error: str | None = None


def run_pipeline(
    fetch_result: FetchResult,
    client: LLMClient,
    *,
    source: Source | None = None,
    max_input_chars: int = 30_000,
    max_chars: int = 1200,
    prompt_versions: Mapping[str, str] | None = None,
) -> PipelineResult:
    prompts = dict(PROMPT_VERSIONS if prompt_versions is None else prompt_versions)
    versions: dict[str, object] = {
        "cleaner": None,
        "pdf_extractor": None,
        "segmenter": SEGMENTER_VERSION,
        "verifier": VERIFIER_VERSION,
        "prompts": prompts,
        "model": None,
        "provider": None,
    }

    def unavailable(status: str, error: str) -> PipelineResult:
        return PipelineResult(status, None, None, None, versions, error)

    if fetch_result.status != "ok" or fetch_result.content is None:
        return unavailable(fetch_result.status, fetch_result.error or "no fetched content")
    content = fetch_result.content
    digest = hashlib.sha256(content).hexdigest()
    if fetch_result.content_sha256 is not None and digest != fetch_result.content_sha256:
        raise ValueError("fetch content_sha256 does not match original bytes")
    media_type = (fetch_result.content_type or "").split(";", 1)[0].strip().lower()
    cleaned: CleanedHTML | ExtractedPDF
    kind: Literal["html", "pdf"]
    if media_type == "text/html":
        kind = "html"
        versions["cleaner"] = CLEANER_VERSION
        cleaned = clean_html(content)
    elif media_type == "application/pdf":
        kind = "pdf"
        versions["pdf_extractor"] = PDF_EXTRACTOR_VERSION
        cleaned = extract_pdf_text(content)
        if cleaned.status != "ok":
            return unavailable(cleaned.status, f"PDF extraction: {cleaned.status}")
    else:
        return unavailable("unsupported_format", "expected text/html or application/pdf")
    if source is None:
        if not fetch_result.fetched_at:
            raise ValueError("fetch requires fetched_at or explicit source metadata")
        timestamp = datetime.fromisoformat(fetch_result.fetched_at)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        source = Source(
            url=fetch_result.url,
            retrieved_on=timestamp.astimezone(UTC).date().isoformat(),
            content_sha256=digest,
            format=kind,
            page_state="unknown",
        )
    if source.content_sha256 != digest or source.format != kind:
        raise ValueError("source hash/format does not match the input")
    doc = segment(cleaned, max_chars=max_chars)
    if not doc.passages:
        return unavailable("empty_text", doc.unsupported_reason or "no cleaned text")
    extraction = extract_record(
        doc, client, source=source, max_input_chars=max_input_chars, prompt_versions=prompts
    )
    final, report = verify_record(extraction.record, doc)
    versions.update(model=extraction.model, provider=extraction.provider)
    status = (
        "failed"
        if len(extraction.failed_groups) == len(prompts)
        else ("partial" if extraction.failed_groups or extraction.rejected_items else "ok")
    )
    return PipelineResult(status, final, extraction, report, versions)
