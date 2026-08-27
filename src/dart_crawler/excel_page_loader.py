from dart_crawler.excel_contract_errors import (
    ExcelFailureReason,
    excel_failure,
)
from dart_crawler.excel_cursor import CursorSecret, ExcelCursorPayload
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import (
    EXCEL_PAGE_BUDGET_BYTES,
    ExcelPage,
    ExcelProvenance,
)
from dart_crawler.excel_page_selection import (
    ExcelPageSelection,
    NormalizedExcelDataset,
    select_excel_page,
)
from dart_crawler.excel_query_service import ExcelQueryServiceFactory
from dart_crawler.excel_request_validation import (
    PreparedExcelRequest,
    prepare_excel_request,
)
from dart_crawler.mcp_wire import measure_excel_result_wire
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset as CompleteExcelDataset,
)
from dart_crawler.result import JsonValue, Result, WarningInfo


def execute_excel_page_request(
    raw_request: JsonValue,
    *,
    cursor_secret: CursorSecret,
    factory: ExcelQueryServiceFactory,
) -> Result[ExcelPage]:
    prepared_result = prepare_excel_request(
        raw_request,
        cursor_secret=cursor_secret,
    )
    prepared = prepared_result.data
    if prepared is None:
        return _preserve_failure(prepared_result)
    return execute_prepared_excel_page(
        prepared,
        cursor_secret=cursor_secret,
        factory=factory,
    )


def execute_prepared_excel_page(
    prepared: PreparedExcelRequest,
    *,
    cursor_secret: CursorSecret,
    factory: ExcelQueryServiceFactory,
) -> Result[ExcelPage]:
    dataset_result = execute_normalized_excel_query(prepared.request, factory)
    dataset = dataset_result.data
    if dataset is None:
        return _preserve_failure(dataset_result)
    cursor = prepared.cursor_payload
    resume_failure = _validate_resume(cursor, dataset)
    if resume_failure is not None:
        return resume_failure
    row_offset = 0 if cursor is None else cursor.offset
    page_index = 0 if cursor is None else cursor.page_index
    page_dataset = NormalizedExcelDataset(
        columns=dataset.columns,
        rows=dataset.rows,
        source_fingerprint=dataset.source_fingerprint,
        warnings=dataset.warnings,
        provenance=ExcelProvenance(
            source=dataset.provenance.source,
            source_fingerprint=dataset.source_fingerprint,
        ),
    )
    page_result = select_excel_page(
        ExcelPageSelection(
            dataset=page_dataset,
            domain=dataset.domain,
            request_fingerprint=dataset.request_fingerprint,
            row_offset=row_offset,
            page_index=page_index,
            page_size=prepared.request.page_size,
            cursor_secret=cursor_secret,
        )
    )
    page = page_result.data
    if page is None:
        return page_result
    return Result[ExcelPage].success(
        page,
        warnings=page_result.warnings,
        next_action=dataset_result.next_action,
    )


def _preserve_failure[SourceT](result: Result[SourceT]) -> Result[ExcelPage]:
    if result.error is None:
        return excel_failure("invalid_request")
    return Result[ExcelPage].failure(
        result.error,
        warnings=result.warnings,
        next_action=result.next_action,
    )


def _validate_resume(
    cursor: ExcelCursorPayload | None,
    dataset: CompleteExcelDataset,
) -> Result[ExcelPage] | None:
    if cursor is None:
        return None
    if cursor.source_fingerprint != dataset.source_fingerprint:
        return _postquery_failure("source_changed", dataset.warnings)
    if (
        cursor.offset <= 0
        or cursor.offset >= dataset.total_rows
        or cursor.page_index <= 0
        or cursor.page_index > cursor.offset
        or cursor.offset > cursor.page_index * cursor.page_size
    ):
        return _postquery_failure("cursor_position_invalid", dataset.warnings)
    return None


def _postquery_failure(
    reason: ExcelFailureReason,
    warnings: tuple[WarningInfo, ...],
) -> Result[ExcelPage]:
    with_warnings: Result[ExcelPage] = excel_failure(reason, warnings=warnings)
    if measure_excel_result_wire(with_warnings).fits_strictly(
        EXCEL_PAGE_BUDGET_BYTES
    ):
        return with_warnings
    without_warnings: Result[ExcelPage] = excel_failure(reason)
    measure_excel_result_wire(without_warnings)
    return without_warnings
