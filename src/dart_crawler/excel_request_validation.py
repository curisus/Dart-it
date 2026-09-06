from __future__ import annotations

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dart_crawler.excel_argument_validation import validate_excel_query
from dart_crawler.excel_contract_errors import ExcelFailureReason, excel_failure
from dart_crawler.excel_cursor import (
    CursorBinding,
    CursorSecret,
    ExcelCursorPayload,
    decode_excel_cursor,
)
from dart_crawler.excel_dataset_identity import normalized_request_fingerprint
from dart_crawler.excel_page_models import ExcelLoadRequest
from dart_crawler.result import JsonValue, Result

_FINGERPRINT_PATTERN: Final = r"^[0-9a-f]{64}$"


class ValidatedExcelRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    request: ExcelLoadRequest
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)


class PreparedExcelRequest(ValidatedExcelRequest):
    cursor_payload: ExcelCursorPayload | None = None


def validate_excel_request(
    raw_request: JsonValue,
) -> Result[ValidatedExcelRequest]:
    try:
        request = ExcelLoadRequest.model_validate(raw_request)
    except ValidationError as error:
        failure: Result[ValidatedExcelRequest] = excel_failure(
            _validation_reason(error)
        )
        return failure
    validated = validate_excel_query(request.domain, request.arguments)
    if validated.data is None:
        return excel_failure("invalid_request")
    request_fingerprint = normalized_request_fingerprint(
        validated.data.domain,
        validated.data.arguments,
    )
    return Result[ValidatedExcelRequest].success(
        ValidatedExcelRequest(
            request=request,
            request_fingerprint=request_fingerprint,
        )
    )


def bind_excel_cursor(
    validated: ValidatedExcelRequest,
    *,
    cursor_secret: CursorSecret,
) -> Result[PreparedExcelRequest]:
    if validated.request.cursor is None:
        return Result[PreparedExcelRequest].success(
            PreparedExcelRequest.model_validate(validated.model_dump())
        )
    decoded = decode_excel_cursor(
        validated.request.cursor,
        secret=cursor_secret,
        binding=CursorBinding(
            request_fingerprint=validated.request_fingerprint,
            page_size=validated.request.page_size,
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
            request=validated.request,
            request_fingerprint=validated.request_fingerprint,
            cursor_payload=decoded.data,
        )
    )


def prepare_excel_request(
    raw_request: JsonValue,
    *,
    cursor_secret: CursorSecret,
) -> Result[PreparedExcelRequest]:
    validated = validate_excel_request(raw_request)
    if validated.data is None:
        if validated.error is None:
            return excel_failure("invalid_request")
        return Result[PreparedExcelRequest].failure(
            validated.error,
            warnings=validated.warnings,
            next_action=validated.next_action,
        )
    return bind_excel_cursor(validated.data, cursor_secret=cursor_secret)


def _validation_reason(error: ValidationError) -> ExcelFailureReason:
    """Name the one request error a caller can act on without guessing.

    Every other malformed request is answered as invalid_request, but a page
    size over the limit is a single number the caller chose and can lower, so
    it is worth saying which field and which limit.
    """
    for detail in error.errors():
        location = detail.get("loc", ())
        if (
            location
            and location[0] == "page_size"
            # Only the upper bound. A page size that is the wrong type, or
            # below one, is not a limit the caller can lower.
            and detail.get("type") == "less_than_equal"
        ):
            return "page_size_exceeds_limit"
    return "invalid_request"
