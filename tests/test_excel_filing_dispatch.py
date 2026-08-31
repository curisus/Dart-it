from dataclasses import replace

from dart_crawler.domain import Filing, ReportKind, ReportPeriod
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import (
    ErrorCode,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.LIST_REPORT_FILINGS,
        arguments={"corp_code": "00123456", "report_kind": "audit"},
        page_size=100,
    )


def _filing(rcept_no: str, fiscal_year: int) -> Filing:
    return Filing(
        corp_code="00123456",
        company_name=f"회사-{fiscal_year}",
        report_kind=ReportKind.AUDIT,
        report_period=ReportPeriod.FY,
        fiscal_year=fiscal_year,
        report_name="사업보고서",
        rcept_no=rcept_no,
        receipt_date=f"{fiscal_year}0331",
    )


def test_list_report_filings_preserves_source_order_and_baseline_columns() -> None:
    source: Result[tuple[Filing, ...]] = Result.success(
        (
            _filing("20260101000002", 2025),
            _filing("20250101000001", 2024),
        )
    )
    responses = replace(
        empty_excel_service_responses(),
        list_report_filings=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "corp_code",
        "report_kind",
        "company_name",
        "report_period",
        "fiscal_year",
        "report_name",
        "rcept_no",
        "receipt_date",
        "correction_chain",
        "withdrawn",
    )
    assert tuple(row["fiscal_year"] for row in result.data.rows) == (2025, 2024)
    assert len(factory.services[0].calls) == 1


def test_list_report_filings_empty_retains_baseline_columns() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns[:2] == ("corp_code", "report_kind")
    assert "company_name" in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_list_report_filings_preserves_existing_failure_without_rows() -> None:
    warning = WarningInfo(
        code=WarningCode.PARTIAL_COLLECTION,
        message="source warning",
    )
    error = error_info(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "source failed",
        retryable=True,
        details={"public": "detail"},
    )
    source = Result[tuple[Filing, ...]].failure(
        error,
        warnings=(warning,),
        next_action="retry",
    )
    responses = replace(
        empty_excel_service_responses(),
        list_report_filings=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.warnings == (warning,)
    assert result.next_action == "retry"
    assert len(factory.services[0].calls) == 1
