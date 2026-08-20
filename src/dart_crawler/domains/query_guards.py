"""Shared input validation and response-size guards for domain services.

Every domain service (financials, topics, ...) validates its inputs before
making any network call and rejects oversized responses instead of
truncating them, so guards live here once instead of being re-derived per
service. A guard cannot return ``Result[SpecificT]`` itself because it is
shared by services with different payload types; it returns a
:class:`GuardViolation` (or ``None`` when the input is fine) and leaves the
conversion to ``Result.failure(...)`` to the calling service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from dart_crawler.result import ErrorCode, ErrorInfo, JsonObject, error_info

# Kept as sorted tuples (rather than frozensets) so the same values that
# drive membership checks can be embedded in ErrorInfo.details without a
# sorted()-return-type mismatch against the invariant JsonValue list type.
VALID_REPRT_CODES: Final[tuple[str, ...]] = ("11011", "11012", "11013", "11014")
MIN_BSNS_YEAR: Final = 2015
VALID_FS_DIVS: Final[tuple[str, ...]] = ("CFS", "OFS")
VALID_IDX_CL_CODES: Final[tuple[str, ...]] = (
    "M210000",
    "M220000",
    "M230000",
    "M240000",
)
MAX_COMPANIES_PER_QUERY: Final = 10
MAX_TOPICS_PER_QUERY: Final = 10
# Rows are ~20 fields wide; 1,000 rows x 20 fields ~= the 20,000-cell budget
# that section_models.MAX_RESPONSE_CELLS enforces for report sections.
MAX_RESPONSE_ROWS: Final = 1_000

_CORP_CODE_PATTERN: Final = re.compile(r"^\d{8}$", re.ASCII)
_SEARCH_COMPANIES_NEXT_ACTION: Final = "search_companies로 corp_code(8자리)를 확인하세요."


@dataclass(frozen=True, slots=True)
class GuardViolation:
    """One shared-guard failure, ready for a service to become a failed Result."""

    error: ErrorInfo
    next_action: str | None = None


def guard_reprt_code(reprt_code: str) -> GuardViolation | None:
    """Reject a report code outside the four DART quarterly/annual codes."""
    if reprt_code in VALID_REPRT_CODES:
        return None
    details: JsonObject = {"supported_reprt_codes": list(VALID_REPRT_CODES)}
    return GuardViolation(
        error_info(
            ErrorCode.INVALID_INPUT,
            "reprt_code가 지원 범위에 없습니다.",
            retryable=False,
            details=details,
        ),
        next_action="11011, 11012, 11013, 11014 중 하나를 입력하세요.",
    )


def guard_bsns_year(bsns_year: int) -> GuardViolation | None:
    """Reject a business year earlier than OpenDART's coverage start.

    Future years intentionally pass through: OpenDART itself answers with
    status 013 (no data found) rather than rejecting the request.
    """
    if bsns_year >= MIN_BSNS_YEAR:
        return None
    return GuardViolation(
        error_info(
            ErrorCode.INVALID_INPUT,
            "bsns_year가 OpenDART 제공 범위보다 이릅니다.",
            retryable=False,
            details={"minimum_bsns_year": MIN_BSNS_YEAR},
        ),
        next_action=f"{MIN_BSNS_YEAR}년 이후 사업연도를 입력하세요.",
    )


def guard_fs_div(fs_div: str) -> GuardViolation | None:
    """Reject a financial-statement scope other than OFS(별도)/CFS(연결)."""
    if fs_div in VALID_FS_DIVS:
        return None
    fs_div_details: JsonObject = {"supported_fs_divs": list(VALID_FS_DIVS)}
    return GuardViolation(
        error_info(
            ErrorCode.INVALID_INPUT,
            "fs_div가 지원 범위에 없습니다.",
            retryable=False,
            details=fs_div_details,
        ),
        next_action="OFS(별도) 또는 CFS(연결) 중 하나를 입력하세요.",
    )


def guard_idx_cl_code(idx_cl_code: str) -> GuardViolation | None:
    """Reject an index class code outside the four DS003 index classes."""
    if idx_cl_code in VALID_IDX_CL_CODES:
        return None
    idx_cl_details: JsonObject = {
        "supported_idx_cl_codes": list(VALID_IDX_CL_CODES)
    }
    return GuardViolation(
        error_info(
            ErrorCode.INVALID_INPUT,
            "idx_cl_code가 지원 범위에 없습니다.",
            retryable=False,
            details=idx_cl_details,
        ),
        next_action=(
            "M210000(수익성), M220000(안정성), M230000(성장성), "
            "M240000(활동성) 중 하나를 입력하세요."
        ),
    )


def guard_corp_code(corp_code: str) -> GuardViolation | None:
    """Reject a single corp_code that is not exactly 8 ASCII digits."""
    if _is_corp_code(corp_code):
        return None
    return GuardViolation(
        error_info(
            ErrorCode.INVALID_INPUT,
            "corp_code 형식이 올바르지 않습니다.",
            retryable=False,
            details={"corp_code": corp_code},
        ),
        next_action=_SEARCH_COMPANIES_NEXT_ACTION,
    )


def guard_corp_codes(corp_codes: tuple[str, ...]) -> GuardViolation | None:
    """Reject an empty, oversized, or malformed corp_code tuple."""
    if not corp_codes:
        return GuardViolation(
            error_info(
                ErrorCode.INVALID_INPUT,
                "corp_codes가 비어 있습니다.",
                retryable=False,
            ),
            next_action=_SEARCH_COMPANIES_NEXT_ACTION,
        )
    if len(corp_codes) > MAX_COMPANIES_PER_QUERY:
        return GuardViolation(
            error_info(
                ErrorCode.INVALID_INPUT,
                "corp_codes 개수가 한 번에 조회할 수 있는 한도를 초과했습니다.",
                retryable=False,
                details={
                    "corp_code_count": len(corp_codes),
                    "limit": MAX_COMPANIES_PER_QUERY,
                },
            ),
            next_action="회사를 나누어 호출하세요.",
        )
    malformed = tuple(code for code in corp_codes if not _is_corp_code(code))
    if malformed:
        return GuardViolation(
            error_info(
                ErrorCode.INVALID_INPUT,
                "corp_code 형식이 올바르지 않습니다.",
                retryable=False,
                details={"invalid_corp_codes": list(malformed)},
            ),
            next_action=_SEARCH_COMPANIES_NEXT_ACTION,
        )
    return None


def guard_row_count(
    row_count: int,
    *,
    next_action: str | None = None,
) -> GuardViolation | None:
    """Reject a response that would carry more rows than the response budget.

    The caller is expected to split its request rather than receive a
    truncated response, so this never trims rows itself.
    """
    if row_count <= MAX_RESPONSE_ROWS:
        return None
    return GuardViolation(
        error_info(
            ErrorCode.INVALID_INPUT,
            "응답 행 수가 한 번에 반환할 수 있는 한도를 초과했습니다.",
            retryable=False,
            details={"returned_row_count": row_count, "limit": MAX_RESPONSE_ROWS},
        ),
        next_action=next_action,
    )


def _is_corp_code(value: str) -> bool:
    return _CORP_CODE_PATTERN.match(value) is not None
