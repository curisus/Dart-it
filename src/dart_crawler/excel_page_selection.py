from __future__ import annotations

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from dart_crawler.excel_contract_errors import ExcelFailureReason, excel_failure
from dart_crawler.excel_cursor import (
    CursorSecret,
    ExcelCursorPayload,
    encode_excel_cursor,
)
from dart_crawler.excel_page_models import (
    EXCEL_PAGE_BUDGET_BYTES,
    MAX_EXCEL_PAGE_SIZE,
    ExcelDataDomain,
    ExcelPage,
    ExcelProvenance,
    ExcelRow,
)
from dart_crawler.mcp_wire import (
    measure_excel_result_wire,
    measure_excel_schema_wire,
)
from dart_crawler.result import Result, WarningInfo

_FINGERPRINT_PATTERN: Final = r"^[0-9a-f]{64}$"


class NormalizedExcelDataset(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]
    source_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    warnings: tuple[WarningInfo, ...] = ()
    provenance: ExcelProvenance = Field(default_factory=ExcelProvenance)


class ExcelPageSelection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    dataset: NormalizedExcelDataset
    domain: ExcelDataDomain
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    row_offset: int = Field(ge=0)
    page_index: int = Field(ge=0)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_SIZE)
    cursor_secret: CursorSecret


def select_excel_page(selection: ExcelPageSelection) -> Result[ExcelPage]:
    available = selection.dataset.rows[
        selection.row_offset : selection.row_offset + selection.page_size
    ]
    candidate = _build_page(selection, available)
    candidate_result = _success_result(candidate, selection.dataset.warnings)
    schema_report = measure_excel_schema_wire(candidate_result)
    if not schema_report.fits_strictly(EXCEL_PAGE_BUDGET_BYTES):
        return _budget_failure(
            "dataset_schema_exceeds_page_budget",
            selection.dataset.warnings,
        )
    fitting_candidate = _success_that_fits(
        candidate,
        selection.dataset.warnings,
    )
    if fitting_candidate is not None:
        return fitting_candidate
    return _greatest_fitting_prefix(selection, available)


def _greatest_fitting_prefix(
    selection: ExcelPageSelection,
    available: tuple[ExcelRow, ...],
) -> Result[ExcelPage]:
    reaches_end = (
        selection.row_offset + len(available) >= len(selection.dataset.rows)
    )
    high = len(available) - 1 if reaches_end else len(available)
    low = 1
    best: Result[ExcelPage] | None = None
    while low <= high:
        middle = (low + high) // 2
        page = _build_page(selection, available[:middle])
        fitting_result = _success_that_fits(
            page,
            selection.dataset.warnings,
        )
        if fitting_result is not None:
            best = fitting_result
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        return _budget_failure(
            "row_exceeds_page_budget",
            selection.dataset.warnings,
        )
    return best


def _build_page(
    selection: ExcelPageSelection,
    rows: tuple[ExcelRow, ...],
) -> ExcelPage:
    dataset = selection.dataset
    next_offset = selection.row_offset + len(rows)
    next_cursor = None
    if next_offset < len(dataset.rows):
        payload = ExcelCursorPayload(
            request_fingerprint=selection.request_fingerprint,
            source_fingerprint=dataset.source_fingerprint,
            offset=next_offset,
            page_index=selection.page_index + 1,
            page_size=selection.page_size,
        )
        next_cursor = encode_excel_cursor(
            payload,
            secret=selection.cursor_secret,
        )
    return ExcelPage(
        domain=selection.domain,
        request_fingerprint=selection.request_fingerprint,
        source_fingerprint=dataset.source_fingerprint,
        columns=dataset.columns,
        rows=rows,
        warnings=(),
        provenance=dataset.provenance,
        total_rows=len(dataset.rows),
        offset=selection.row_offset,
        page_index=selection.page_index,
        page_size=selection.page_size,
        returned_rows=len(rows),
        next_cursor=next_cursor,
    )


def _success_result(
    page: ExcelPage,
    warnings: tuple[WarningInfo, ...],
) -> Result[ExcelPage]:
    return Result[ExcelPage].success(page.model_copy(update={"warnings": warnings}))


def _success_that_fits(
    page: ExcelPage,
    warnings: tuple[WarningInfo, ...],
) -> Result[ExcelPage] | None:
    with_warnings = _success_result(page, warnings)
    report = measure_excel_result_wire(with_warnings)
    if report.fits_strictly(EXCEL_PAGE_BUDGET_BYTES):
        return with_warnings
    return None


def _budget_failure(
    reason: ExcelFailureReason,
    warnings: tuple[WarningInfo, ...],
) -> Result[ExcelPage]:
    with_warnings: Result[ExcelPage] = excel_failure(reason, warnings=warnings)
    report = measure_excel_result_wire(with_warnings)
    if report.fits_strictly(EXCEL_PAGE_BUDGET_BYTES):
        return with_warnings
    without_warnings: Result[ExcelPage] = excel_failure(reason)
    _ = measure_excel_result_wire(without_warnings)
    return without_warnings
