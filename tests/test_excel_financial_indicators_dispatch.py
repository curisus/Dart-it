from dataclasses import replace

from dart_crawler.api_models import FinancialIndexRow
from dart_crawler.domains.financials import FinancialIndicatorData
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_CORP_CODES = ("00123456", "00654321")


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_FINANCIAL_INDICATORS,
        arguments={
            "corp_codes": list(_CORP_CODES),
            "bsns_year": 2025,
            "reprt_code": "11011",
            "idx_cl_code": "M210000",
        },
        page_size=100,
    )


def _row(corp_code: str, name: str) -> FinancialIndexRow:
    return FinancialIndexRow(
        bsns_year="2025",
        corp_code=corp_code,
        idx_cl_code="M210000",
        idx_cl_nm="수익성지표",
        idx_nm=name,
        idx_val="12.34",
    )


def _data(rows: tuple[FinancialIndexRow, ...]) -> FinancialIndicatorData:
    return FinancialIndicatorData(
        corp_codes=_CORP_CODES,
        bsns_year=2025,
        reprt_code="11011",
        idx_cl_code="M210000",
        returned_row_count=len(rows),
        empty_indicator_count=sum(1 for row in rows if not row.idx_val.strip()),
        indicators=rows,
    )


def test_financial_indicators_preserve_source_order_and_index_context() -> None:
    rows = (_row(_CORP_CODES[1], "ROE"), _row(_CORP_CODES[0], "ROA"))
    responses = replace(
        empty_excel_service_responses(),
        get_financial_indicators=Result.success(_data(rows)),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns[:4] == (
        "corp_codes",
        "bsns_year",
        "reprt_code",
        "idx_cl_code",
    )
    assert tuple(row["idx_nm"] for row in result.data.rows) == ("ROE", "ROA")
    assert result.data.rows[0]["idx_cl_code"] == "M210000"
    assert "source_bsns_year" in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_financial_indicators_empty_retains_declared_columns() -> None:
    source = Result.success(_data(()))
    responses = replace(
        empty_excel_service_responses(),
        get_financial_indicators=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert "idx_nm" in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_financial_indicators_preserve_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_AUTH,
        "authentication failed",
        retryable=False,
    )
    source = Result[FinancialIndicatorData].failure(error, next_action="check key")
    responses = replace(
        empty_excel_service_responses(),
        get_financial_indicators=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "check key"
    assert len(factory.services[0].calls) == 1
