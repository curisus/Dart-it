"""Atomic Markdown generation from the normalized document model.

Unlike the XLSX exporter, a missing core statement never blocks the export:
the whole parsed document is rendered as-is, and a missing statement only
downgrades ``collection_status`` and adds a warning. The parse-level
integrity gate (``validate_document``) still fails hard, because a document
that failed coverage or table-shape validation cannot be trusted at all.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from dart_crawler.document_model import BlockKind, DocumentBlock, DocumentSection
from dart_crawler.document_validation import validate_document
from dart_crawler.excel_export import CollectionStatus, ExportContext
from dart_crawler.output_file import next_available_path, safe_filename
from dart_crawler.result import (
    ErrorCode,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from dart_crawler.section_models import missing_core_sections, summarize_sections

_IMAGE_PLACEHOLDER = "[이미지 내용 생략]"
_EMPTY_SECTION_PLACEHOLDER = "_내용 없음_"
_METADATA_START = "<!-- dart-crawler:metadata"
_METADATA_END = "-->"
_RCEPT_NO_KEY = "rcept_no"
_ATTACHMENT_ID_KEY = "attachment_id"
_SOURCE_SHA256_KEY = "source_sha256"


class MarkdownExportedFile(BaseModel):
    """Observable result of one Markdown export attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_path: Path
    collection_status: CollectionStatus
    reused: bool
    missing_sections: tuple[str, ...]
    source_sha256: str
    rendered_section_count: int
    rendered_table_count: int
    rendered_char_count: int


class MarkdownExportService:
    """Render one whole parsed attachment to a single Markdown file."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def export(self, context: ExportContext) -> Result[MarkdownExportedFile]:
        """Validate parse integrity, then render every section without truncation."""
        document_validation = validate_document(context.document)
        if not document_validation.ok:
            return Result.failure(
                document_validation.error
                if document_validation.error is not None
                else error_info(
                    ErrorCode.VALIDATION_FAILED,
                    "원문 구조 검증 결과를 확인할 수 없습니다.",
                    retryable=False,
                ),
                next_action=document_validation.next_action,
            )
        missing = missing_core_sections(context.document)
        has_image = any(
            block.kind is BlockKind.IMAGE
            for section in context.document.sections
            for block in section.blocks
        )
        status = (
            CollectionStatus.PARTIAL
            if missing or has_image
            else CollectionStatus.COMPLETE
        )
        warnings: list[WarningInfo] = list(
            context.comparison_warnings + context.collection_warnings
        )
        if status is CollectionStatus.PARTIAL:
            warnings.append(
                WarningInfo(
                    code=WarningCode.PARTIAL_COLLECTION,
                    message="일부 내용을 완전히 수집하지 못한 채로 마크다운을 생성했습니다.",
                    details={"missing_sections": list(missing)} if missing else {},
                )
            )
            if has_image:
                warnings.append(
                    WarningInfo(
                        code=WarningCode.IMAGE_CONTENT_SKIPPED,
                        message="OCR을 수행하지 않아 이미지 내용을 자리표시자로 남겼습니다.",
                    )
                )
        output_path = self._output_path(context, status)
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return Result.failure(
                error_info(
                    ErrorCode.OUTPUT_WRITE_FAILED,
                    "출력 폴더를 만들 수 없습니다.",
                    retryable=False,
                    details={"reason": str(exc)},
                )
            )
        summaries = summarize_sections(context.document)
        rendered_section_count = len(summaries)
        rendered_table_count = sum(summary.table_count for summary in summaries)
        # Rendering is deterministic, so the length of the rendered document
        # equals what the written (or previously written, hence reused) file
        # holds — counted here once so both return paths report it.
        content = _render_document(context, status)
        rendered_char_count = len(content)
        if _matching_existing_file(output_path, context):
            warnings.append(
                WarningInfo(
                    code=WarningCode.EXISTING_FILE_REUSED,
                    message="접수번호, 첨부 식별자, 원문 SHA-256이 같은 기존 파일을 재사용했습니다.",
                )
            )
            return Result.success(
                MarkdownExportedFile(
                    output_path=output_path,
                    collection_status=status,
                    reused=True,
                    missing_sections=missing,
                    source_sha256=context.document.source_sha256,
                    rendered_section_count=rendered_section_count,
                    rendered_table_count=rendered_table_count,
                    rendered_char_count=rendered_char_count,
                ),
                warnings=tuple(warnings),
            )
        output_path = next_available_path(output_path, context)
        try:
            _write_markdown(output_path, content)
        except OSError as exc:
            return Result.failure(
                error_info(
                    ErrorCode.OUTPUT_WRITE_FAILED,
                    "마크다운 파일을 저장할 수 없습니다.",
                    retryable=False,
                    details={"reason": str(exc)},
                )
            )
        return Result.success(
            MarkdownExportedFile(
                output_path=output_path,
                collection_status=status,
                reused=False,
                missing_sections=missing,
                source_sha256=context.document.source_sha256,
                rendered_section_count=rendered_section_count,
                rendered_table_count=rendered_table_count,
                rendered_char_count=rendered_char_count,
            ),
            warnings=tuple(warnings),
        )

    def _output_path(self, context: ExportContext, status: CollectionStatus) -> Path:
        report_date = context.report_date or context.receipt_date
        partial_suffix = "_부분수집" if status is CollectionStatus.PARTIAL else ""
        filename = (
            f"{context.company_name}_{report_date} {context.report_title}_"
            f"{context.receipt_date}{partial_suffix}.md"
        )
        return self._output_dir / safe_filename(filename)


def _write_markdown(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=".tmp",
        mode="w",
        encoding="utf-8",
        newline="",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _matching_existing_file(path: Path, context: ExportContext) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    values = _parse_metadata_block(text)
    return (
        values.get(_RCEPT_NO_KEY) == context.rcept_no
        and values.get(_ATTACHMENT_ID_KEY) == context.attachment_id
        and values.get(_SOURCE_SHA256_KEY) == context.document.source_sha256
    )


def _parse_metadata_block(text: str) -> dict[str, str]:
    if not text.startswith(_METADATA_START):
        return {}
    end_index = text.find(_METADATA_END, len(_METADATA_START))
    if end_index == -1:
        return {}
    block = text[len(_METADATA_START) : end_index]
    values: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        values[key.strip()] = value.strip()
    return values


def _render_document(context: ExportContext, status: CollectionStatus) -> str:
    lines = [
        _metadata_comment(context, status),
        "",
        f"# {_document_title(context)}",
        "",
    ]
    for section in context.document.sections:
        lines.extend(_render_section(section))
    return "\n".join(lines).rstrip("\n") + "\n"


def _metadata_comment(context: ExportContext, status: CollectionStatus) -> str:
    return "\n".join(
        [
            _METADATA_START,
            f"{_RCEPT_NO_KEY}: {context.rcept_no}",
            f"{_ATTACHMENT_ID_KEY}: {context.attachment_id}",
            f"{_SOURCE_SHA256_KEY}: {context.document.source_sha256}",
            f"collection_status: {status.value}",
            _METADATA_END,
        ]
    )


def _document_title(context: ExportContext) -> str:
    report_date = context.report_date or context.receipt_date
    return f"{context.company_name} {context.report_title} ({report_date})"


def _render_section(section: DocumentSection) -> list[str]:
    lines = [f"## {section.title} ({section.kind.value})", ""]
    if not section.blocks:
        lines.append(_EMPTY_SECTION_PLACEHOLDER)
        lines.append("")
        return lines
    for block in section.blocks:
        lines.extend(_render_block(block))
        lines.append("")
    return lines


def _render_block(block: DocumentBlock) -> list[str]:
    if block.kind is BlockKind.TABLE:
        return _render_table(block.rows)
    if block.kind is BlockKind.IMAGE:
        return [_image_placeholder(block.image_source)]
    return [_normalize_newlines(block.text)]


def _image_placeholder(image_source: str | None) -> str:
    if image_source:
        return f"{_IMAGE_PLACEHOLDER}: {image_source}"
    return _IMAGE_PLACEHOLDER


def _render_table(rows: tuple[tuple[str, ...], ...]) -> list[str]:
    if not rows:
        return [_EMPTY_SECTION_PLACEHOLDER]
    width = max(len(row) for row in rows)
    lines = [_table_row(rows[0], width), _table_separator(width)]
    lines.extend(_table_row(row, width) for row in rows[1:])
    return lines


def _table_row(row: tuple[str, ...], width: int) -> str:
    cells = [_escape_cell(cell) for cell in row]
    cells.extend([""] * (width - len(cells)))
    return "| " + " | ".join(cells) + " |"


def _table_separator(width: int) -> str:
    return "| " + " | ".join(["---"] * width) + " |"


def _escape_cell(text: str) -> str:
    normalized = _normalize_newlines(text)
    return normalized.replace("|", "\\|").replace("\n", "<br>")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
