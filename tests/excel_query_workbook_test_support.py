from dart_crawler.excel_page_models import ExcelDataDomain, ExcelRow
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import WarningInfo


def make_normalized_dataset(
    columns: tuple[str, ...],
    rows: tuple[ExcelRow, ...],
    *,
    warnings: tuple[WarningInfo, ...] = (),
) -> NormalizedExcelDataset:
    total_rows = len(rows)
    domain = ExcelDataDomain.SEARCH_COMPANIES
    return NormalizedExcelDataset(
        domain=domain,
        validated_arguments={"company_query": "테스트"},
        request_fingerprint="1" * 64,
        source_fingerprint="2" * 64,
        dataset_id="3" * 64,
        columns=columns,
        rows=rows,
        warnings=warnings,
        provenance=NormalizedExcelProvenance(
            domain=domain,
            source_rows=total_rows,
            normalized_rows=total_rows,
        ),
        total_rows=total_rows,
    )
