from dart_crawler.domain import Company
from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
    preserve_excel_failure,
)
from dart_crawler.excel_json_models import (
    model_columns,
    model_json_object,
)
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_row_normalization import PendingExcelRow
from dart_crawler.excel_source_values import json_object_pairs
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result


def normalize_search_companies(
    arguments: SearchCompaniesArguments,
    result: Result[tuple[Company, ...]],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    context = (
        ("company_query", arguments.company_query),
        ("report_kind", arguments.report_kind),
    )
    rows = tuple(
        PendingExcelRow(context, json_object_pairs(model_json_object(company)))
        for company in result.data
    )
    provenance = NormalizedExcelProvenance(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        source_rows=len(result.data),
        normalized_rows=len(rows),
    )
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.SEARCH_COMPANIES,
            arguments=arguments,
            context_columns=("company_query", "report_kind"),
            source_columns=model_columns(Company),
            rows=rows,
            warnings=result.warnings,
            provenance=provenance,
            next_action=result.next_action,
        )
    )
