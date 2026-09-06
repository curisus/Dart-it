from dataclasses import replace

from dart_crawler.api_models import FinancialAccount
from dart_crawler.domains.financials import FinancialStatementData
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
        arguments={
            "corp_code": "00123456",
            "bsns_year": 2025,
            "reprt_code": "11011",
        },
        page_size=100,
    )


def _account(name: str, order: str) -> FinancialAccount:
    return FinancialAccount(
        fs_div="CFS",
        sj_div="BS",
        bsns_year="2025",
        reprt_code="11011",
        account_id=f"ifrs-{order}",
        account_nm=name,
        thstrm_amount=order,
        corp_code="00123456",
        ord=order,
    )


def _data(accounts: tuple[FinancialAccount, ...]) -> FinancialStatementData:
    return FinancialStatementData(
        corp_code="00123456",
        bsns_year=2025,
        reprt_code="11011",
        fs_div="CFS",
        returned_row_count=len(accounts),
        accounts=accounts,
    )


def test_financial_statements_preserve_order_and_typed_collision() -> None:
    source = Result.success(_data((_account("현금", "1"), _account("매출", "2"))))
    responses = replace(
        empty_excel_service_responses(),
        get_financial_statements=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.validated_arguments["fs_div"] == "CFS"
    assert result.data.columns[:4] == (
        "corp_code",
        "bsns_year",
        "reprt_code",
        "fs_div",
    )
    assert "source_bsns_year" in result.data.columns
    assert result.data.rows[0]["bsns_year"] == 2025
    assert result.data.rows[0]["source_bsns_year"] == "2025"
    assert tuple(row["account_nm"] for row in result.data.rows) == ("현금", "매출")
    assert len(factory.services[0].calls) == 1


def test_financial_statements_empty_retains_account_columns() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert "account_nm" in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_financial_statements_do_not_trust_misleading_reported_count() -> None:
    source = FinancialStatementData(
        corp_code="00123456",
        bsns_year=2025,
        reprt_code="11011",
        fs_div="CFS",
        returned_row_count=999,
        accounts=(_account("현금", "1"),),
    )
    responses = replace(
        empty_excel_service_responses(),
        get_financial_statements=Result.success(source),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.total_rows == 1
    assert result.data.provenance.normalized_rows == 1
    assert result.data.provenance.reported_rows == 999
    assert len(factory.services[0].calls) == 1


def test_financial_statements_preserve_existing_failure() -> None:
    error = error_info(
        ErrorCode.NOT_FOUND,
        "no consolidated statements",
        retryable=False,
    )
    source = Result[FinancialStatementData].failure(
        error,
        next_action="use OFS",
    )
    responses = replace(
        empty_excel_service_responses(),
        get_financial_statements=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "use OFS"
    assert len(factory.services[0].calls) == 1


def test_financial_statements_report_amounts_as_numbers() -> None:
    """Text amounts cannot be summed, sorted, or pivoted in a spreadsheet."""
    source = Result.success(
        _data((_account("현금", "1,000"), _account("매출", "2,500,000")))
    )
    responses = replace(
        empty_excel_service_responses(),
        get_financial_statements=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.numeric_columns == ("thstrm_amount",)
    assert [row["thstrm_amount"] for row in result.data.rows] == [1000, 2500000]


def test_financial_statements_keep_identifier_columns_as_text() -> None:
    """corp_code and rcept_no are digit strings that must not lose a leading zero."""
    source = Result.success(_data((_account("현금", "1,000"),)))
    responses = replace(
        empty_excel_service_responses(),
        get_financial_statements=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert "corp_code" not in result.data.numeric_columns
    assert "source_bsns_year" not in result.data.numeric_columns
    assert result.data.rows[0]["corp_code"] == "00123456"
    assert result.data.rows[0]["source_bsns_year"] == "2025"
