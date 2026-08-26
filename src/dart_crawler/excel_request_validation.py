from __future__ import annotations

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dart_crawler.excel_contract_errors import excel_failure
from dart_crawler.excel_cursor import (
    CursorBinding,
    CursorSecret,
    ExcelCursorPayload,
    decode_excel_cursor,
    fingerprint_excel_request,
)
from dart_crawler.excel_page_models import ExcelLoadRequest
from dart_crawler.result import JsonObject, Result

_FINGERPRINT_PATTERN: Final = r"^[0-9a-f]{64}$"


class PreparedExcelRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    request: ExcelLoadRequest
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    cursor_payload: ExcelCursorPayload | None = None


def prepare_excel_request(
    raw_request: JsonObject,
    *,
    cursor_secret: CursorSecret,
) -> Result[PreparedExcelRequest]:
    try:
        request = ExcelLoadRequest.model_validate(raw_request)
    except ValidationError:
        failure: Result[PreparedExcelRequest] = excel_failure("invalid_request")
        return failure
    request_fingerprint = fingerprint_excel_request(request)
    if request.cursor is None:
        return Result[PreparedExcelRequest].success(
            PreparedExcelRequest(
                request=request,
                request_fingerprint=request_fingerprint,
            )
        )
    decoded = decode_excel_cursor(
        request.cursor,
        secret=cursor_secret,
        binding=CursorBinding(
            request_fingerprint=request_fingerprint,
            page_size=request.page_size,
        ),
    )
    if decoded.data is None:
        if decoded.error is None:
            return excel_failure("invalid_cursor")
        return Result[PreparedExcelRequest].failure(
            decoded.error,
            warnings=decoded.warnings,
            next_action=decoded.next_action,
        )
    return Result[PreparedExcelRequest].success(
        PreparedExcelRequest(
            request=request,
            request_fingerprint=request_fingerprint,
            cursor_payload=decoded.data,
        )
    )
