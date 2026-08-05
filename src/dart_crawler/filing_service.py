"""Regular-report filtering and correction-series consolidation."""

from __future__ import annotations

import re
from typing import Protocol

from dart_crawler.api_models import DartListRow
from dart_crawler.domain import Filing, ReportKind, ReportPeriod
from dart_crawler.result import ErrorCode, Result, error_info


class FilingSource(Protocol):
    """OpenDART capability required by filing listing."""

    def list_disclosures(
        self,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        raise NotImplementedError


class FilingService:
    """Create the five-year filing view required by the MCP contract."""

    def __init__(self, source: FilingSource) -> None:
        self._source = source

    def list(
        self,
        corp_code: str,
        company_name: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Filing, ...]]:
        """List valid representative filings for one company."""
        try:
            parsed_kind = ReportKind(report_kind)
        except ValueError:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "report_kind가 지원 범위에 없습니다.",
                    retryable=False,
                )
            )
        source_result = self._source.list_disclosures(
            corp_code, _detail_type(parsed_kind)
        )
        if not source_result.ok or source_result.data is None:
            return Result.failure(
                source_result.error
                if source_result.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "공시 목록을 수집할 수 없습니다.",
                    retryable=True,
                ),
                next_action="잠시 후 공시 목록을 다시 요청하세요.",
            )
        groups: dict[tuple[int, ReportPeriod, str], list[DartListRow]] = {}
        for row in source_result.data:
            parsed = _parse_period(parsed_kind, row.report_nm, row.rcept_dt)
            if parsed is None:
                continue
            fiscal_year, period = parsed
            key = (fiscal_year, period, _base_report_name(row.report_nm))
            groups.setdefault(key, []).append(row)
        filings: list[Filing] = []
        for (fiscal_year, period, report_name), rows in sorted(
            groups.items(),
            key=lambda item: (-item[0][0], _period_order(item[0][1]), item[0][2]),
        ):
            active_rows = [row for row in rows if "철" not in row.rm]
            if not active_rows:
                continue
            representative = max(
                active_rows, key=lambda row: (row.rcept_dt, row.rcept_no)
            )
            filings.append(
                Filing(
                    corp_code=corp_code,
                    company_name=company_name,
                    report_kind=parsed_kind,
                    report_period=period,
                    fiscal_year=fiscal_year,
                    report_name=report_name,
                    rcept_no=representative.rcept_no,
                    receipt_date=representative.rcept_dt,
                    correction_chain=tuple(
                        row.rcept_no
                        for row in sorted(rows, key=lambda row: row.rcept_no)
                    ),
                )
            )
        return Result.success(tuple(_limit_years(filings)))


def _detail_type(report_kind: ReportKind) -> str:
    return {
        ReportKind.AUDIT: "A001",
        ReportKind.HALF_YEAR_REVIEW: "A002",
        ReportKind.QUARTERLY_REVIEW: "A003",
    }[report_kind]


def _parse_period(
    report_kind: ReportKind,
    report_name: str,
    receipt_date: str,
) -> tuple[int, ReportPeriod] | None:
    if not matches_report_kind(report_kind, report_name):
        return None
    year_match = re.search(r"20\d{2}", report_name)
    year = int(year_match.group()) if year_match else int(receipt_date[:4])
    if report_kind is ReportKind.AUDIT:
        return year, ReportPeriod.FY
    if report_kind is ReportKind.HALF_YEAR_REVIEW:
        return year, ReportPeriod.HALF_YEAR
    month_match = re.search(r"20\d{2}\.(\d{2})", report_name)
    month = month_match.group(1) if month_match else ""
    if "1분기" in report_name or month == "03":
        return year, ReportPeriod.FIRST_QUARTER
    if "3분기" in report_name or month == "09":
        return year, ReportPeriod.THIRD_QUARTER
    return None


def matches_report_kind(report_kind: ReportKind, report_name: str) -> bool:
    """Check a report title when OpenDART returns a broader result set."""
    if report_kind is ReportKind.AUDIT:
        return "사업보고서" in report_name or "감사보고서" in report_name
    if report_kind is ReportKind.HALF_YEAR_REVIEW:
        return "반기" in report_name and "분기" not in report_name
    return "분기" in report_name


def _base_report_name(report_name: str) -> str:
    return re.sub(r"^(?:\[(?:기재정정|첨부정정|첨부추가|정정)\]\s*)+", "", report_name)


def _period_order(period: ReportPeriod) -> int:
    return {
        ReportPeriod.FY: 0,
        ReportPeriod.HALF_YEAR: 0,
        ReportPeriod.FIRST_QUARTER: 1,
        ReportPeriod.THIRD_QUARTER: 2,
    }[period]


def _limit_years(filings: list[Filing]) -> list[Filing]:
    years = sorted({filing.fiscal_year for filing in filings}, reverse=True)[:5]
    return [filing for filing in filings if filing.fiscal_year in years]
