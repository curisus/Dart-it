from __future__ import annotations

from pathlib import Path

import dart_crawler.excel_query_workbook_writer as workbook_writer
from dart_crawler.excel_export_result import (
    ExcelCleanupWarningCode,
    ExcelExportWarningInfo,
    Result,
)
from dart_crawler.excel_native_projection import ExcelProjectionFailure
from dart_crawler.excel_output_safety import (
    SafeOutputRoot,
    UnsafeOutputPath,
    is_safe_output_child,
    path_exists,
    prepare_safe_output_root,
)
from dart_crawler.excel_publication_file_ops import (
    SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    CandidateUnavailable,
    CleanupFailed,
    ExcelPublicationFileOps,
    FileOperationFailed,
    LinkOutcome,
    OwnedFile,
    is_current_regular_file,
    publish_owned_link,
)
from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.excel_query_workbook_plan import (
    EXCEL_MAX_COLUMNS,
    ExcelClock,
    ExcelWorkbookOptions,
    ExcelWorkbookPlan,
    build_excel_workbook_plan,
)
from dart_crawler.excel_query_workbook_validation import (
    WorkbookValidationFailure,
    validate_excel_query_workbook,
)
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import ErrorCode, error_info


def publish_excel_dataset(
    dataset: NormalizedExcelDataset,
    output_root: Path,
    *,
    clock: ExcelClock,
    options: ExcelWorkbookOptions,
    file_ops: ExcelPublicationFileOps = SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    next_action: str | None = None,
) -> Result[ExcelExportResult]:
    if len(dataset.columns) > EXCEL_MAX_COLUMNS:
        return _validation_failure("excel_column_limit_exceeded")
    root_outcome = prepare_safe_output_root(output_root)
    if isinstance(root_outcome, UnsafeOutputPath):
        return _output_failure()
    plan = build_excel_workbook_plan(dataset, clock, options)
    suffix = 1
    while True:
        filename = (
            f"{dataset.domain.value}.xlsx"
            if suffix == 1
            else f"{dataset.domain.value}_{suffix}.xlsx"
        )
        final_path = root_outcome.path / filename
        lock_path = final_path.with_suffix(final_path.suffix + ".lock")
        if not _candidate_is_safe(root_outcome, final_path, lock_path):
            return _output_failure()
        if path_exists(final_path):
            suffix += 1
            continue
        lock_outcome = file_ops.acquire_lock(lock_path)
        if isinstance(lock_outcome, CandidateUnavailable):
            suffix += 1
            continue
        if isinstance(lock_outcome, FileOperationFailed):
            return _output_failure()
        result = _publish_owned_candidate(
            root_outcome,
            final_path,
            lock_outcome.file,
            plan,
            file_ops,
            next_action,
        )
        if result is None:
            suffix += 1
            continue
        return result


def _publish_owned_candidate(
    root: SafeOutputRoot,
    final_path: Path,
    lock_file: OwnedFile,
    plan: ExcelWorkbookPlan,
    file_ops: ExcelPublicationFileOps,
    next_action: str | None,
) -> Result[ExcelExportResult] | None:
    if path_exists(final_path):
        _cleanup_before_publish(None, lock_file, file_ops)
        return None
    temp_outcome = file_ops.create_temp(
        root.path,
        prefix=f".{final_path.stem}.",
    )
    if isinstance(temp_outcome, FileOperationFailed):
        _cleanup_before_publish(None, lock_file, file_ops)
        return _output_failure()
    temp_file = temp_outcome.file
    temp_path = temp_file.path
    if not is_safe_output_child(root, temp_path):
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return _output_failure()
    try:
        written = workbook_writer.write_excel_query_workbook(temp_path, plan)
    except OSError:
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return _output_failure()
    if isinstance(written, ExcelProjectionFailure):
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return _validation_failure(written.reason)
    validated = validate_excel_query_workbook(temp_path, plan)
    if isinstance(validated, WorkbookValidationFailure):
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return _validation_failure(validated.reason)
    link_outcome: LinkOutcome = publish_owned_link(
        file_ops, temp_file, final_path
    )
    if isinstance(link_outcome, CandidateUnavailable):
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return None
    if isinstance(link_outcome, FileOperationFailed):
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return _output_failure()
    published_failure = _published_workbook_failure(link_outcome.file, plan)
    if published_failure is not None:
        _ = file_ops.unlink_owned(link_outcome.file)
        _cleanup_before_publish(temp_file, lock_file, file_ops)
        return published_failure
    cleanup_warnings = _cleanup_after_publish(temp_file, lock_file, file_ops)
    return Result[ExcelExportResult].success(
        ExcelExportResult(
            absolute_path=str(final_path),
            filename=final_path.name,
            dataset_id=plan.dataset.dataset_id,
            total_rows=plan.dataset.total_rows,
            sheet_names=plan.sheet_names,
        ),
        warnings=cleanup_warnings,
        next_action=next_action,
    )


def _candidate_is_safe(
    root: SafeOutputRoot,
    final_path: Path,
    lock_path: Path,
) -> bool:
    return is_safe_output_child(root, final_path) and is_safe_output_child(
        root, lock_path
    )


def _published_workbook_failure(
    published_file: OwnedFile,
    plan: ExcelWorkbookPlan,
) -> Result[ExcelExportResult] | None:
    validation = validate_excel_query_workbook(published_file.path, plan)
    if isinstance(validation, WorkbookValidationFailure):
        return _validation_failure(validation.reason)
    if not is_current_regular_file(published_file):
        return _output_failure()
    return None


def _cleanup_before_publish(
    temp_file: OwnedFile | None,
    lock_file: OwnedFile,
    file_ops: ExcelPublicationFileOps,
) -> None:
    if temp_file is not None:
        _ = file_ops.unlink_owned(temp_file)
    _ = file_ops.unlink_owned(lock_file)


def _cleanup_after_publish(
    temp_file: OwnedFile,
    lock_file: OwnedFile,
    file_ops: ExcelPublicationFileOps,
) -> tuple[ExcelExportWarningInfo, ...]:
    warnings: list[ExcelExportWarningInfo] = []
    temp_cleanup = file_ops.unlink_owned(temp_file)
    if isinstance(temp_cleanup, CleanupFailed):
        warnings.append(
            ExcelExportWarningInfo(
                code=ExcelCleanupWarningCode.OUTPUT_TEMP_CLEANUP_FAILED,
                message="임시 Excel 파일 정리에 실패했습니다.",
            )
        )
    lock_cleanup = file_ops.unlink_owned(lock_file)
    if isinstance(lock_cleanup, CleanupFailed):
        warnings.append(
            ExcelExportWarningInfo(
                code=ExcelCleanupWarningCode.OUTPUT_LOCK_CLEANUP_FAILED,
                message="Excel 잠금 파일 정리에 실패했습니다.",
            )
        )
    return tuple(warnings)


def _output_failure() -> Result[ExcelExportResult]:
    return Result[ExcelExportResult].failure(
        error_info(
            ErrorCode.OUTPUT_WRITE_FAILED,
            "Excel 파일을 안전하게 저장할 수 없습니다.",
            retryable=False,
            details={"reason": "output_write_failed"},
        )
    )


def _validation_failure(reason: str) -> Result[ExcelExportResult]:
    return Result[ExcelExportResult].failure(
        error_info(
            ErrorCode.VALIDATION_FAILED,
            "Excel 파일 검증에 실패했습니다.",
            retryable=False,
            details={"reason": reason},
        )
    )
