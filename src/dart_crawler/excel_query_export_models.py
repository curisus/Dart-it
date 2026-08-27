from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dart_crawler.excel_argument_validation import validate_excel_query
from dart_crawler.excel_contract_errors import excel_failure
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import JsonObject, JsonValue, Result

_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


class ExcelExportRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    domain: ExcelDataDomain
    arguments: JsonObject


class ExcelExportResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    absolute_path: str
    filename: str
    dataset_id: str = Field(pattern=_FINGERPRINT_PATTERN)
    total_rows: int = Field(ge=0, strict=True)
    sheet_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedExcelExportRequest:
    request: ExcelLoadRequest


def prepare_excel_export_request(
    raw_request: JsonValue,
) -> Result[PreparedExcelExportRequest]:
    try:
        request = ExcelExportRequest.model_validate(raw_request)
    except ValidationError:
        return excel_failure("invalid_request")
    validated = validate_excel_query(request.domain, request.arguments)
    if validated.data is None:
        return excel_failure("invalid_request")
    return Result[PreparedExcelExportRequest].success(
        PreparedExcelExportRequest(
            request=ExcelLoadRequest(
                domain=request.domain,
                arguments=request.arguments,
            )
        )
    )
