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
from dart_crawler.result import ErrorCode, Result, error_info

_CFS_NOT_FOUND_NEXT_ACTION: Final = (
    '연결재무제표가 없는 회사일 수 있습니다. fs_div="OFS"(별도)로 다시 시도하세요.'
)
_SPLIT_COMPANIES_NEXT_ACTION: Final = "회사를 나누어 호출하세요."


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

    def __init__(self, source: FinancialSource) -> None:
        self._source = source

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

        row_violation = guard_row_count(len(fetched.data))
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
            guard_corp_codes(corp_codes)
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
            guard_corp_codes(corp_codes)
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
            warnings=fetched.warnings,
        )
