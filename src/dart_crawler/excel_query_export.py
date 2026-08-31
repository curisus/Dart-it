from pathlib import Path

from dart_crawler.excel_export_result import Result, export_warning_from_core
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_query_export_models import (
    ExcelExportResult,
    PreparedExcelExportRequest,
)
from dart_crawler.excel_query_service import ExcelQueryServiceFactory
from dart_crawler.excel_query_workbook_plan import ExcelClock, ExcelWorkbookOptions
from dart_crawler.excel_safe_publication import publish_excel_dataset


def execute_prepared_excel_export(
    prepared: PreparedExcelExportRequest,
    *,
    factory: ExcelQueryServiceFactory,
    output_root: Path,
    clock: ExcelClock,
    options: ExcelWorkbookOptions,
) -> Result[ExcelExportResult]:
    dataset_result = execute_normalized_excel_query(prepared.request, factory)
    if dataset_result.data is None:
        if dataset_result.error is None:
            return Result[ExcelExportResult].model_validate(dataset_result)
        return Result[ExcelExportResult].failure(
            dataset_result.error,
            warnings=tuple(
                export_warning_from_core(warning)
                for warning in dataset_result.warnings
            ),
            next_action=dataset_result.next_action,
        )
    return publish_excel_dataset(
        dataset_result.data,
        output_root,
        clock=clock,
        options=options,
        next_action=dataset_result.next_action,
    )
