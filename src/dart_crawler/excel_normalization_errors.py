from typing import Literal

from dart_crawler.result import ErrorCode, ErrorInfo, error_info

type NormalizationFailureReason = Literal[
    "unsupported_cell_value",
    "non_finite_number",
]


def normalization_error(reason: NormalizationFailureReason) -> ErrorInfo:
    return error_info(
        ErrorCode.VALIDATION_FAILED,
        "엑셀 데이터 요청을 정규화할 수 없습니다.",
        retryable=False,
        details={"reason": reason},
    )
