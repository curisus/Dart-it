from dart_crawler.result import ErrorCode, ErrorInfo, Result, WarningCode, WarningInfo


def test_success_result_contains_data_and_next_action() -> None:
    result = Result.success(
        {"value": "ready"},
        warnings=(
            WarningInfo(code=WarningCode.FALLBACK_SOURCE_USED, message="fallback"),
        ),
        next_action="call_next",
    )

    assert result.ok is True
    assert result.data == {"value": "ready"}
    assert result.error is None
    assert result.next_action == "call_next"
    assert result.warnings[0].code is WarningCode.FALLBACK_SOURCE_USED


def test_failure_result_contains_structured_error() -> None:
    error = ErrorInfo(
        code=ErrorCode.INVALID_INPUT,
        message="report_kind is invalid",
        retryable=False,
    )

    result: Result[ErrorInfo] = Result.failure(error, next_action="correct_input")

    assert result.ok is False
    assert result.data is None
    assert result.error == error
    assert result.next_action == "correct_input"
