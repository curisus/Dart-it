"""DS003 financial-statement, major-account, and index lookups."""

from __future__ import annotations

from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.api_models import FinancialAccount, FinancialIndexRow, MajorAccountRow
from dart_crawler.dart_api import FinancialQuery
from dart_crawler.domains.query_guards import (
    guard_bsns_year,
    guard_corp_code,
    guard_corp_codes,
    guard_fs_div,
    guard_idx_cl_code,
    guard_reprt_code,
    guard_row_count,
)
from dart_crawler.query_limits import DEFAULT_QUERY_LIMITS, QueryLimits
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    JsonValue,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)

# OpenDART answers "no data" with one status for every reason, so a missing
# consolidated statement and a wrong year or report code arrive identically.
# The wording therefore offers the retry without asserting the cause: the
# 2026-09-06 campaign followed the old text, retried with OFS, and hit the
# same NOT_FOUND because the year simply had no statements at all.
_CFS_NOT_FOUND_NEXT_ACTION: Final = (
    "해당 회사·사업연도의 재무제표를 찾지 못했습니다. "
    '연결재무제표가 없는 회사라면 fs_div="OFS"(별도)로, '
    "그래도 없으면 다른 bsns_year 또는 reprt_code로 확인하세요."
)
_SPLIT_COMPANIES_NEXT_ACTION: Final = "회사를 나누어 호출하세요."
# Indicator names listed in the warning; a longer list is counted, not spelled
# out, so one warning cannot outgrow the response it describes.
_MAX_LISTED_EMPTY_INDICATORS: Final = 20


class FinancialSource(Protocol):
    """OpenDART capabilities required by the financials domain service."""

    def fetch_financial_accounts(
        self,
        query: FinancialQuery,
    ) -> Result[tuple[FinancialAccount, ...]]:
        raise NotImplementedError

    def fetch_major_accounts(
        self,
        corp_codes: tuple[str, ...],
        business_year: int,
        report_code: str,
    ) -> Result[tuple[MajorAccountRow, ...]]:
        raise NotImplementedError

    def fetch_financial_indexes(
        self,
        corp_codes: tuple[str, ...],
        business_year: int,
        report_code: str,
        index_class: str,
    ) -> Result[tuple[FinancialIndexRow, ...]]:
        raise NotImplementedError


class FinancialStatementData(BaseModel):
    """Every account row DART reports for one company and filing period."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str
    bsns_year: int
    reprt_code: str
    fs_div: str
    returned_row_count: int
    accounts: tuple[FinancialAccount, ...]


class MajorAccountData(BaseModel):
    """DS003 major-account rows for one or more companies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_codes: tuple[str, ...]
    bsns_year: int
    reprt_code: str
    returned_row_count: int
    accounts: tuple[MajorAccountRow, ...]


class FinancialIndicatorData(BaseModel):
    """DS003 financial-index rows for one or more companies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_codes: tuple[str, ...]
    bsns_year: int
    reprt_code: str
    idx_cl_code: str
    returned_row_count: int
    indicators: tuple[FinancialIndexRow, ...]


class FinancialsService:
    """Validate, fetch, and size-guard DS003 financial-data requests."""

    def __init__(
        self,
        source: FinancialSource,
        *,
        limits: QueryLimits = DEFAULT_QUERY_LIMITS,
    ) -> None:
        self._source: FinancialSource = source
        self._limits: QueryLimits = limits

    def full_statements(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        fs_div: str,
    ) -> Result[FinancialStatementData]:
        """Return every OFS or CFS account row for one filing period."""
        violation = (
            guard_corp_code(corp_code)
            or guard_reprt_code(reprt_code)
            or guard_bsns_year(bsns_year)
            or guard_fs_div(fs_div)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        query = FinancialQuery(
            corp_code=corp_code,
            business_year=bsns_year,
            report_code=reprt_code,
            statement_scope=fs_div,
        )
        fetched = self._source.fetch_financial_accounts(query)
        if not fetched.ok or fetched.data is None:
            if (
                fs_div == "CFS"
                and fetched.error is not None
                and fetched.error.code is ErrorCode.NOT_FOUND
            ):
                return Result.failure(
                    fetched.error,
                    warnings=fetched.warnings,
                    next_action=_CFS_NOT_FOUND_NEXT_ACTION,
                )
            return Result.failure(
                fetched.error
                if fetched.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 전체 계정과목을 수집할 수 없습니다.",
                    retryable=True,
                ),
                warnings=fetched.warnings,
                next_action=fetched.next_action,
            )

        row_violation = guard_row_count(len(fetched.data), limits=self._limits)
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        return Result.success(
            FinancialStatementData(
                corp_code=corp_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                fs_div=fs_div,
                returned_row_count=len(fetched.data),
                accounts=fetched.data,
            ),
            warnings=fetched.warnings,
        )

    def major_accounts(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
    ) -> Result[MajorAccountData]:
        """Return DS003 major-account rows for one or more companies."""
        violation = (
            guard_corp_codes(corp_codes, limits=self._limits)
            or guard_reprt_code(reprt_code)
            or guard_bsns_year(bsns_year)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        fetched = self._source.fetch_major_accounts(corp_codes, bsns_year, reprt_code)
        if not fetched.ok or fetched.data is None:
            return Result.failure(
                fetched.error
                if fetched.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 주요계정 재무정보를 수집할 수 없습니다.",
                    retryable=True,
                ),
                warnings=fetched.warnings,
                next_action=fetched.next_action,
            )

        row_violation = guard_row_count(
            len(fetched.data),
            limits=self._limits,
            next_action=_SPLIT_COMPANIES_NEXT_ACTION,
        )
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        return Result.success(
            MajorAccountData(
                corp_codes=corp_codes,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                returned_row_count=len(fetched.data),
                accounts=fetched.data,
            ),
            warnings=fetched.warnings,
        )

    def indicators(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
        idx_cl_code: str,
    ) -> Result[FinancialIndicatorData]:
        """Return DS003 financial-index rows for one or more companies."""
        violation = (
            guard_corp_codes(corp_codes, limits=self._limits)
            or guard_reprt_code(reprt_code)
            or guard_bsns_year(bsns_year)
            or guard_idx_cl_code(idx_cl_code)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        fetched = self._source.fetch_financial_indexes(
            corp_codes,
            bsns_year,
            reprt_code,
            idx_cl_code,
        )
        if not fetched.ok or fetched.data is None:
            return Result.failure(
                fetched.error
                if fetched.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 재무지표를 수집할 수 없습니다.",
                    retryable=True,
                ),
                warnings=fetched.warnings,
                next_action=fetched.next_action,
            )

        row_violation = guard_row_count(
            len(fetched.data),
            limits=self._limits,
            next_action=_SPLIT_COMPANIES_NEXT_ACTION,
        )
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        return Result.success(
            FinancialIndicatorData(
                corp_codes=corp_codes,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                idx_cl_code=idx_cl_code,
                returned_row_count=len(fetched.data),
                indicators=fetched.data,
            ),
            warnings=fetched.warnings + _empty_indicator_warnings(fetched.data),
        )


def _empty_indicator_warnings(
    indicators: tuple[FinancialIndexRow, ...],
) -> tuple[WarningInfo, ...]:
    """Report indicators OpenDART returned with no value.

    A blank idx_val is indistinguishable from a collection failure once the
    rows reach a spreadsheet, and the 2026-09-06 campaign saw 28% of indicator
    rows arrive blank with nothing said about it.
    """
    empty: list[JsonValue] = [
        row.idx_nm for row in indicators if not row.idx_val.strip()
    ]
    if not empty:
        return ()
    details: JsonObject = {
        "empty_indicator_count": len(empty),
        "empty_indicators": empty[:_MAX_LISTED_EMPTY_INDICATORS],
    }
    return (
        WarningInfo(
            code=WarningCode.PARTIAL_COLLECTION,
            message="일부 지표는 OpenDART가 값 없이 반환했습니다.",
            details=details,
        ),
    )
