from dataclasses import replace

from dart_crawler.domains.ownership import OwnershipReportData
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, JsonObject, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_OWNERSHIP_REPORTS,
        arguments={
            "corp_code": "00123456",
            "report_type": "major_holding",
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
        page_size=100,
    )


def _data(rows: tuple[JsonObject, ...]) -> OwnershipReportData:
    return OwnershipReportData(
        corp_code="00123456",
        report_type="major_holding",
        label="대량보유",
        bgn_de="20250101",
        end_de="20251231",
        total_row_count=7,
        returned_row_count=len(rows),
        rows=rows,
    )


def test_ownership_rows_preserve_order_dynamic_columns_and_counts() -> None:
    first: JsonObject = {"holder": "둘째", "shares": 2}
    second: JsonObject = {"holder": "첫째", "ratio": "1"}
    source = Result.success(_data((first, second)))
    responses = replace(
        empty_excel_service_responses(),
        get_ownership_reports=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "corp_code",
        "report_type",
        "label",
        "bgn_de",
        "end_de",
        "holder",
        "shares",
        "ratio",
    )
    assert tuple(row["holder"] for row in result.data.rows) == ("둘째", "첫째")
    assert result.data.provenance.reported_total_rows == 7
    assert result.data.provenance.reported_rows == 2
    assert len(factory.services[0].calls) == 1


def test_ownership_empty_retains_context_baseline() -> None:
    source = Result.success(_data(()))
    responses = replace(
        empty_excel_service_responses(),
        get_ownership_reports=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns == (
        "corp_code",
        "report_type",
        "label",
        "bgn_de",
        "end_de",
    )
    assert len(factory.services[0].calls) == 1


def test_ownership_preserves_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "ownership failed",
        retryable=True,
    )
    source = Result[OwnershipReportData].failure(error, next_action="retry")
    responses = replace(
        empty_excel_service_responses(),
        get_ownership_reports=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "retry"
    assert len(factory.services[0].calls) == 1
