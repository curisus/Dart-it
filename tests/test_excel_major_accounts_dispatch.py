from dataclasses import replace

from dart_crawler.api_models import MajorAccountRow
from dart_crawler.domains.financials import MajorAccountData
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_CORP_CODES = ("00123456", "00654321")


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments={
            "corp_codes": list(_CORP_CODES),
            "bsns_year": 2025,
            "reprt_code": "11011",
        },
        page_size=100,
    )


def _row(corp_code: str, account_name: str) -> MajorAccountRow:
    return MajorAccountRow(
        reprt_code="11011",
        bsns_year="2025",
        corp_code=corp_code,
        fs_div="CFS",
        sj_div="BS",
        account_nm=account_name,
    )


def _data(rows: tuple[MajorAccountRow, ...]) -> MajorAccountData:
    return MajorAccountData(
        corp_codes=_CORP_CODES,
        bsns_year=2025,
        reprt_code="11011",
        returned_row_count=len(rows),
        accounts=rows,
    )


def test_major_accounts_preserve_raw_order_and_canonical_company_context() -> None:
    rows = (_row(_CORP_CODES[1], "매출"), _row(_CORP_CODES[0], "현금"))
    responses = replace(
        empty_excel_service_responses(),
        get_major_accounts=Result.success(_data(rows)),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns[:3] == ("corp_codes", "bsns_year", "reprt_code")
    assert result.data.rows[0]["corp_codes"] == '["00123456","00654321"]'
    assert tuple(row["corp_code"] for row in result.data.rows) == (
        "00654321",
        "00123456",
    )
    assert len(factory.services[0].calls) == 1
    assert factory.services[0].calls[0].arguments["corp_codes"] == list(_CORP_CODES)


def test_major_accounts_empty_retains_raw_account_columns() -> None:
    source = Result.success(_data(()))
    responses = replace(
        empty_excel_service_responses(),
        get_major_accounts=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert "account_nm" in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_major_accounts_preserve_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_RATE_LIMIT,
        "rate limited",
        retryable=True,
    )
    source = Result[MajorAccountData].failure(error, next_action="retry later")
    responses = replace(
        empty_excel_service_responses(),
        get_major_accounts=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "retry later"
    assert len(factory.services[0].calls) == 1
