"""Private snapshot files and public hash-only metadata (ADR 007); no fetching.

Raw bytes/text never enter SnapshotRecord or the public manifest. Cleaned hashes
collapse whitespace only: no verifier normalization, rewriting or case folding.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from scholarscope.cleaner import CLEANER_VERSION, CleanedHTML, clean_html
from scholarscope.fetcher import FetchResult
from scholarscope.pdf_text import PDF_EXTRACTOR_VERSION, ExtractedPDF, PDFStatus, extract_pdf_text
from scholarscope.segmenter import SEGMENTER_VERSION, segment

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = ROOT / "eval/snapshots"
MANIFEST_PATH = ROOT / "eval/manifest.json"
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN)]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[str, StringConstraints(min_length=1)]
HTTPURL = Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]
Drift = Literal["unchanged", "benign_raw_change", "content_changed", "tool_version_changed"]


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SnapshotRecord(_Metadata):
    """Public metadata only; `bytes` is a byte COUNT, never the original content."""

    slug: Slug
    url: HTTPURL
    final_url: HTTPURL
    retrieved_on: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    format: Literal["html", "pdf"]
    bytes: Annotated[int, Field(ge=0)]
    content_sha256: SHA256
    cleaned_text_sha256: SHA256
    text_chars: Annotated[int, Field(ge=0)]
    cleaner_version: Version | None
    pdf_extractor_version: Version | None
    segmenter_version: Version
    passage_count: Annotated[int, Field(ge=0)]
    extraction_status: PDFStatus = "ok"

    @field_validator("retrieved_on")
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def matching_tool(self) -> Self:
        if self.format == "html":
            if self.cleaner_version is None or self.pdf_extractor_version is not None:
                raise ValueError("HTML requires only cleaner_version")
            if self.extraction_status != "ok":
                raise ValueError("HTML extraction_status must be ok")
        elif self.pdf_extractor_version is None or self.cleaner_version is not None:
            raise ValueError("PDF requires only pdf_extractor_version")
        return self


class SnapshotManifest(_Metadata):
    schema_version: Literal["0.1"] = "0.1"
    snapshots: dict[str, SnapshotRecord] = Field(default_factory=dict)

    @model_validator(mode="after")
    def matching_keys(self) -> Self:
        if any(key != record.slug for key, record in self.snapshots.items()):
            raise ValueError("manifest key must equal snapshot slug")
        return self


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".snapshot-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def snapshot_page(
    fetch_result: FetchResult, slug: str, *, snapshots_dir: Path = SNAPSHOTS_DIR
) -> SnapshotRecord:
    """Save a successful fetch and its text copy. Replaces that slug's local files.

    Use a separate private directory for re-fetches, never the frozen hand-label
    originals. Reject bad slugs/metadata before writing; all tests use tmp_path.
    Unsupported PDFs retain private bytes and empty text, explicitly flagged.
    """
    # Function-local private text only; never a SnapshotRecord field.
    parsed_source: CleanedHTML | ExtractedPDF
    if not re.fullmatch(SLUG_PATTERN, slug):
        raise ValueError("invalid snapshot slug")
    if fetch_result.status != "ok" or fetch_result.content is None:
        raise ValueError(f"cannot snapshot fetch status {fetch_result.status}")
    if not fetch_result.fetched_at:
        raise ValueError("successful fetch requires fetched_at")
    timestamp = datetime.fromisoformat(fetch_result.fetched_at)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    content = fetch_result.content
    digest = hashlib.sha256(content).hexdigest()
    if fetch_result.content_sha256 is not None and fetch_result.content_sha256 != digest:
        raise ValueError("fetch content_sha256 does not match original bytes")
    media_type = (fetch_result.content_type or "").split(";", 1)[0].strip().lower()
    extraction_status: PDFStatus = "ok"
    cleaner_version: str | None
    pdf_version: str | None
    if media_type == "text/html":
        parsed_source = clean_html(content)
        format_: Literal["html", "pdf"] = "html"
        cleaner_version, pdf_version = CLEANER_VERSION, None
    elif media_type == "application/pdf":
        parsed_source = extract_pdf_text(content)
        extraction_status = parsed_source.status
        format_ = "pdf"
        cleaner_version, pdf_version = None, PDF_EXTRACTOR_VERSION
    else:
        raise ValueError("snapshot requires text/html or application/pdf content type")
    document = segment(parsed_source)
    text = parsed_source.text
    normalized_text = " ".join(text.split())
    record = SnapshotRecord(
        slug=slug,
        url=fetch_result.url,
        final_url=fetch_result.final_url or fetch_result.url,
        retrieved_on=timestamp.astimezone(UTC).date().isoformat(),
        format=format_,
        bytes=len(content),
        content_sha256=digest,
        cleaned_text_sha256=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        text_chars=len(text),
        cleaner_version=cleaner_version,
        pdf_extractor_version=pdf_version,
        segmenter_version=SEGMENTER_VERSION,
        passage_count=len(document.passages),
        extraction_status=extraction_status,
    )
    directory = snapshots_dir.resolve()
    if directory.is_relative_to((ROOT / "eval/gold").resolve()):
        raise ValueError("snapshots must never be written into eval/gold")
    # Atomic replacement also replaces an existing symlink itself, not its target.
    _atomic_write(directory / f"{slug}.{format_}", content)
    _atomic_write(directory / f"{slug}.txt", text.encode("utf-8"))
    return record


def classify_drift(old: SnapshotRecord, new: SnapshotRecord) -> Drift:
    if old.content_sha256 == new.content_sha256:
        return "unchanged"
    old_versions = (old.cleaner_version, old.pdf_extractor_version, old.segmenter_version)
    new_versions = (new.cleaner_version, new.pdf_extractor_version, new.segmenter_version)
    if old_versions != new_versions:
        return "tool_version_changed"
    if old.cleaned_text_sha256 == new.cleaned_text_sha256:
        return "benign_raw_change"
    return "content_changed"


def load_manifest(path: Path = MANIFEST_PATH) -> SnapshotManifest:
    return SnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_manifest(manifest: SnapshotManifest, path: Path = MANIFEST_PATH) -> None:
    """Write only validated, whitelisted metadata; never serialize a FetchResult."""
    # Revalidate even if a caller modified the nested dictionary in a frozen model.
    checked = SnapshotManifest.model_validate(manifest.model_dump())
    ordered = checked.model_copy(update={"snapshots": dict(sorted(checked.snapshots.items()))})
    _atomic_write(path, (ordered.model_dump_json(indent=2) + "\n").encode("utf-8"))
