from pydantic import BaseModel

from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
)
from dart_crawler.excel_json_models import model_columns, model_json_object
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_row_normalization import PendingExcelRow, SourcePairs
from dart_crawler.excel_source_values import json_object_pairs
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result, WarningInfo


def normalize_model_rows[ModelT: BaseModel](
    *,
    domain: ExcelDataDomain,
    arguments: StrictExcelArguments,
    context_columns: tuple[str, ...],
    context: SourcePairs,
    source_model: type[ModelT],
    models: tuple[ModelT, ...],
    warnings: tuple[WarningInfo, ...],
    next_action: str | None,
    provenance: NormalizedExcelProvenance,
) -> Result[NormalizedExcelDataset]:
    rows = tuple(
        PendingExcelRow(context, json_object_pairs(model_json_object(model)))
        for model in models
    )
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=domain,
            arguments=arguments,
            context_columns=context_columns,
            source_columns=model_columns(source_model),
            rows=rows,
            warnings=warnings,
            provenance=provenance,
            next_action=next_action,
        )
    )
