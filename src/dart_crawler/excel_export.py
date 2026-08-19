"""Atomic XLSX generation from the normalized document model."""

from __future__ import annotations

from enum import StrEnum, unique
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from dart_crawler.document_model import BlockKind, ParsedDocument, SectionKind
from dart_crawler.document_validation import validate_document
from dart_crawler.output_file import (
    matching_existing_file,
    next_available_path,
    safe_filename,
)
from dart_crawler.result import (
    ErrorCode,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from dart_crawler.workbook_validation import validate_workbook
from dart_crawler.workbook_writer import write_workbook


@unique
class CollectionStatus(StrEnum):
    """Whether every parsed section was available without image-only content."""

    COMPLETE = "complete"
    PARTIAL = "partial"


@unique
class ValidationStatus(StrEnum):
    """Whether source-to-workbook validation completed successfully."""

    PASSED = "passed"


class ExportContext(BaseModel):
    """Metadata and normalized document selected for one export."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_name: str
    report_date: str | None
    report_title: str
    receipt_date: str
    rcept_no: str
    source_rcept_no: str
    attachment_id: str
    correction_chain: tuple[str, ...]
    source_url: str
    parser_version: str
    document: ParsedDocument
    comparison_warnings: tuple[WarningInfo, ...] = ()
    collection_warnings: tuple[WarningInfo, ...] = ()


class ExportedFile(BaseModel):
    """Observable result of one XLSX export attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_path: Path
    collection_status: CollectionStatus
    reused: bool
    missing_sections: tuple[str, ...]
    source_sha256: str
    validation_status: ValidationStatus
    validated_cell_count: int
    validated_merge_count: int


class ExcelExportService:
    """Write searchable workbook sheets without overwriting different files."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def export(self, context: ExportContext) -> Result[ExportedFile]:
        """Validate core statements and atomically create or reuse a workbook."""
        document_validation = validate_document(context.document)
        if not document_validation.ok or document_validation.data is None:
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
        validation_summary = document_validation.data
        missing = _missing_core_sections(context.document)
        if missing:
            return Result.failure(
                error_info(
                    ErrorCode.CORE_STATEMENT_MISSING,
                    "핵심 재무제표가 누락되어 엑셀을 만들지 않았습니다.",
                    retryable=False,
                    details={"missing_sections": list(missing)},
                ),
                next_action="재무상태표, 손익·포괄손익, 자본변동표, 현금흐름표가 포함된 원문을 선택하세요.",
            )
        status = (
            CollectionStatus.PARTIAL
            if any(
                block.kind is BlockKind.IMAGE
                for section in context.document.sections
                for block in section.blocks
            )
            else CollectionStatus.COMPLETE
        )
        warnings: list[WarningInfo] = list(
            context.comparison_warnings + context.collection_warnings
        )
        if status is CollectionStatus.PARTIAL:
            warnings.append(
                WarningInfo(
                    code=WarningCode.PARTIAL_COLLECTION,
                    message="이미지 전용 구역을 제외하고 엑셀을 생성했습니다.",
                )
            )
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
        reused = matching_existing_file(output_path, context)
        # Reuse alone tolerates a pre-change legacy workbook without the new row.
        existing_validation = (
            validate_workbook(
                output_path,
                context,
                collection_status=status.value,
                summary=validation_summary,
                allow_legacy_source_receipt_omission=True,
            )
            if reused
            else None
        )
        if reused and existing_validation is not None and existing_validation.ok:
            warnings.append(
                WarningInfo(
                    code=WarningCode.EXISTING_FILE_REUSED,
                    message="접수번호, 첨부 식별자, 원문 SHA-256이 같은 기존 파일을 재사용했습니다.",
                )
            )
            return Result.success(
                ExportedFile(
                    output_path=output_path,
                    collection_status=status,
                    reused=True,
                    missing_sections=(),
                    source_sha256=context.document.source_sha256,
                    validation_status=ValidationStatus.PASSED,
                    validated_cell_count=validation_summary.checked_cell_count,
                    validated_merge_count=validation_summary.checked_merge_count,
                ),
                warnings=tuple(warnings),
            )
        output_path = next_available_path(output_path, context)
        try:
            write_workbook(output_path, context, status, validation_summary)
        except OSError as exc:
            return Result.failure(
                error_info(
                    ErrorCode.OUTPUT_WRITE_FAILED,
                    "엑셀 파일을 저장할 수 없습니다.",
                    retryable=False,
                    details={"reason": str(exc)},
                )
            )
        # A newly written workbook must always contain source_rcept_no.
        workbook_validation = validate_workbook(
            output_path,
            context,
            collection_status=status.value,
            summary=validation_summary,
            allow_legacy_source_receipt_omission=False,
        )
        if not workbook_validation.ok:
            try:
                output_path.unlink(missing_ok=True)
            except OSError as exc:
                return Result.failure(
                    error_info(
                        ErrorCode.OUTPUT_WRITE_FAILED,
                        "검증에 실패한 엑셀 파일을 정리할 수 없습니다.",
                        retryable=False,
                        details={"reason": str(exc)},
                    )
                )
            return Result.failure(
                workbook_validation.error
                if workbook_validation.error is not None
                else error_info(
                    ErrorCode.VALIDATION_FAILED,
                    "저장된 엑셀 검증 결과를 확인할 수 없습니다.",
                    retryable=False,
                ),
                next_action=workbook_validation.next_action,
            )
        return Result.success(
            ExportedFile(
                output_path=output_path,
                collection_status=status,
                reused=False,
                missing_sections=(),
                source_sha256=context.document.source_sha256,
                validation_status=ValidationStatus.PASSED,
                validated_cell_count=validation_summary.checked_cell_count,
                validated_merge_count=validation_summary.checked_merge_count,
            ),
            warnings=tuple(warnings),
        )

    def _output_path(self, context: ExportContext, status: CollectionStatus) -> Path:
        report_date = context.report_date or context.receipt_date
        partial_suffix = "_부분수집" if status is CollectionStatus.PARTIAL else ""
        filename = (
            f"{context.company_name}_{report_date} {context.report_title}_"
            f"{context.receipt_date}{partial_suffix}.xlsx"
        )
        return self._output_dir / safe_filename(filename)


def _missing_core_sections(document: ParsedDocument) -> tuple[str, ...]:
    labels = {
        SectionKind.BALANCE_SHEET: "재무상태표",
        SectionKind.INCOME: "손익·포괄손익",
        SectionKind.EQUITY: "자본변동표",
        SectionKind.CASH_FLOW: "현금흐름표",
    }
    missing = []
    for kind, label in labels.items():
        sections = [section for section in document.sections if section.kind is kind]
        if not sections or not any(
            block.kind is BlockKind.TABLE
            for section in sections
            for block in section.blocks
        ):
            missing.append(label)
    return tuple(missing)
