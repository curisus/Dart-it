from typing import Final, Literal, assert_never

from dart_crawler.result import ErrorCode, Result, WarningInfo, error_info

type ExcelFailureReason = Literal[
    "invalid_request",
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


def excel_failure[T](
    reason: ExcelFailureReason,
    *,
    warnings: tuple[WarningInfo, ...] = (),
) -> Result[T]:
    match reason:
        case "invalid_request":
            code = ErrorCode.INVALID_INPUT
            next_action = None
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
        case unreachable:
            assert_never(unreachable)
    return Result[T].failure(
        error_info(
            code,
            "Excel 페이지 요청을 완료할 수 없습니다.",
            retryable=False,
            details={"reason": reason},
        ),
        warnings=warnings,
        next_action=next_action,
    )


def excel_cursor_configuration_failure[T]() -> Result[T]:
    return Result[T].failure(
        error_info(
            ErrorCode.CONFIG_ERROR,
            "Excel 커서 서명 설정을 사용할 수 없습니다.",
            retryable=False,
            details={"reason": "invalid_request"},
        )
    )
