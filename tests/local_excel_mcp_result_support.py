from typing import ClassVar

from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict

from dart_crawler.excel_export_result import Result as ExcelResult
from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.result import JsonObject


class _StructuredCall(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="ignore",
    )

    structured_content: JsonObject


def structured_content(call: CallToolResult) -> JsonObject:
    validated = _StructuredCall.model_validate_json(call.model_dump_json())
    return validated.structured_content


def excel_export_result(
    call: CallToolResult,
) -> ExcelResult[ExcelExportResult]:
    return ExcelResult[ExcelExportResult].model_validate(structured_content(call))
