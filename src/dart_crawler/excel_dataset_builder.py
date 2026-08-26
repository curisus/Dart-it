from dataclasses import dataclass

from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_contract_errors import excel_failure
from dart_crawler.excel_dataset_identity import (
    SourceIdentityState,
    normalized_dataset_id,
    normalized_request_fingerprint,
    normalized_source_fingerprint,
)
from dart_crawler.excel_json_models import model_json_object
from dart_crawler.excel_normalization_errors import normalization_error
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_row_normalization import (
    CellFailure,
    PendingExcelRow,
    normalize_excel_rows,
)
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result, WarningInfo


@dataclass(frozen=True, slots=True)
class ExcelSourceDataset:
    domain: ExcelDataDomain
    arguments: StrictExcelArguments
    context_columns: tuple[str, ...]
    source_columns: tuple[str, ...]
    rows: tuple[PendingExcelRow, ...]
    warnings: tuple[WarningInfo, ...]
    provenance: NormalizedExcelProvenance
    next_action: str | None = None


def normalize_excel_source(
    source: ExcelSourceDataset,
) -> Result[NormalizedExcelDataset]:
    match normalize_excel_rows(
        source.context_columns,
        source.source_columns,
        source.rows,
    ):
        case CellFailure(reason=reason):
            return Result.failure(
                normalization_error(reason),
                warnings=source.warnings,
                next_action=source.next_action,
            )
        case table:
            pass
    request_fingerprint = normalized_request_fingerprint(
        source.domain,
        source.arguments,
    )
    validated_arguments = model_json_object(source.arguments)
    source_fingerprint = normalized_source_fingerprint(
        SourceIdentityState(
            domain=source.domain,
            columns=table.columns,
            rows=table.rows,
            warnings=source.warnings,
            provenance=source.provenance,
        )
    )
    dataset_id = normalized_dataset_id(
        source.domain,
        request_fingerprint,
        source_fingerprint,
    )
    return Result.success(
        NormalizedExcelDataset(
            domain=source.domain,
            validated_arguments=validated_arguments,
            request_fingerprint=request_fingerprint,
            source_fingerprint=source_fingerprint,
            dataset_id=dataset_id,
            columns=table.columns,
            rows=table.rows,
            warnings=source.warnings,
            provenance=source.provenance,
            total_rows=len(table.rows),
        ),
        next_action=source.next_action,
    )


def preserve_excel_failure[T](
    result: Result[T],
) -> Result[NormalizedExcelDataset]:
    error = result.error
    if error is None:
        return excel_failure("invalid_request")
    return Result.failure(
        error,
        warnings=result.warnings,
        next_action=result.next_action,
    )
