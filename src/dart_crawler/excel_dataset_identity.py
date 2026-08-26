import hashlib
from dataclasses import dataclass

from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_canonical_json import canonical_json_bytes
from dart_crawler.excel_json_models import model_json_object
from dart_crawler.excel_page_models import (
    EXCEL_SCHEMA_VERSION,
    ExcelDataDomain,
    ExcelRow,
)
from dart_crawler.normalized_excel_models import NormalizedExcelProvenance
from dart_crawler.result import JsonObject, WarningInfo


@dataclass(frozen=True, slots=True)
class SourceIdentityState:
    domain: ExcelDataDomain
    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]
    warnings: tuple[WarningInfo, ...]
    provenance: NormalizedExcelProvenance


def normalized_request_fingerprint(
    domain: ExcelDataDomain,
    arguments: StrictExcelArguments,
) -> str:
    payload: JsonObject = {
        "schema_version": EXCEL_SCHEMA_VERSION,
        "domain": domain.value,
        "validated_arguments": model_json_object(arguments),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def normalized_source_fingerprint(state: SourceIdentityState) -> str:
    payload: JsonObject = {
        "schema_version": EXCEL_SCHEMA_VERSION,
        "domain": state.domain.value,
        "columns": list(state.columns),
        "rows": [_row_json(row) for row in state.rows],
        "warnings": [model_json_object(warning) for warning in state.warnings],
        "provenance": model_json_object(state.provenance),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _row_json(row: ExcelRow) -> JsonObject:
    return dict(row)


def normalized_dataset_id(
    domain: ExcelDataDomain,
    request_fingerprint: str,
    source_fingerprint: str,
) -> str:
    payload: JsonObject = {
        "schema_version": EXCEL_SCHEMA_VERSION,
        "domain": domain.value,
        "request_fingerprint": request_fingerprint,
        "source_fingerprint": source_fingerprint,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
