from typing import Final, Literal

from dart_crawler.excel_page_models import MAX_EXCEL_PAGE_SIZE
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    Result,
    WarningInfo,
    error_info,
)

type ExcelFailureReason = Literal[
    "invalid_request",
    "page_size_exceeds_limit",
    "invalid_cursor",
    "cursor_schema_mismatch",
    "cursor_request_mismatch",
    "cursor_page_size_mismatch",
    "source_changed",
    "cursor_position_invalid",
    "dataset_schema_exceeds_page_budget",
    "row_exceeds_page_budget",
]

_RESTART_ACTION: Final = "커서 없이 첫 페이지부터 다시 요청하세요."
_EXPORT_ACTION: Final = "전체 결과가 필요하면 export_query_excel을 사용하세요."
_PAGE_SIZE_ACTION: Final = (
    f"page_size를 {MAX_EXCEL_PAGE_SIZE} 이하로 지정하세요."
)


def excel_failure[T](
    reason: ExcelFailureReason,
    *,
    warnings: tuple[WarningInfo, ...] = (),
) -> Result[T]:
    match reason:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
        case "invalid_request":
            code = ErrorCode.INVALID_INPUT
            next_action = None
        case "page_size_exceeds_limit":
            code = ErrorCode.INVALID_INPUT
            next_action = _PAGE_SIZE_ACTION
        case (
            "invalid_cursor"
            | "cursor_schema_mismatch"
            | "cursor_request_mismatch"
            | "cursor_page_size_mismatch"
        ):
            code = ErrorCode.INVALID_INPUT
            next_action = _RESTART_ACTION
        case "source_changed" | "cursor_position_invalid":
            code = ErrorCode.VALIDATION_FAILED
            next_action = _RESTART_ACTION
        case (
            "dataset_schema_exceeds_page_budget"
            | "row_exceeds_page_budget"
        ):
            code = ErrorCode.VALIDATION_FAILED
            next_action = _EXPORT_ACTION
    return Result[T].failure(
        error_info(
            code,
            "Excel 페이지 요청을 완료할 수 없습니다.",
            retryable=False,
            details=_details(reason),
        ),
        warnings=warnings,
        next_action=next_action,
    )


def _details(reason: ExcelFailureReason) -> JsonObject:
    """Return the reason plus the limit a caller needs to satisfy it."""
    details: JsonObject = {"reason": reason}
    if reason == "page_size_exceeds_limit":
        details["max_page_size"] = MAX_EXCEL_PAGE_SIZE
    return details


def excel_cursor_configuration_failure[T]() -> Result[T]:
    return Result[T].failure(
        error_info(
            ErrorCode.CONFIG_ERROR,
            "Excel 커서 서명 설정을 사용할 수 없습니다.",
            retryable=False,
            details={"reason": "invalid_request"},
        )
    )
