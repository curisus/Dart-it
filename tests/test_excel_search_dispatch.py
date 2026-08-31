from dataclasses import replace

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import (
    ErrorCode,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def test_search_companies_dispatch_normalizes_one_source_call() -> None:
    source: Result[tuple[Company, ...]] = Result.success(
        (
            Company(
                company_name="테스트",
                corp_code="00123456",
                stock_code="123456",
                market=Market.KOSPI,
                ranking=1,
                match_confidence=MatchConfidence.EXACT,
            ),
        ),
        warnings=(
            WarningInfo(
                code=WarningCode.FALLBACK_SOURCE_USED,
                message="fallback",
            ),
        ),
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=source,
    )
    factory = RecordingExcelServiceFactory(responses)
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "테스트"},
        page_size=1,
    )

    result = execute_normalized_excel_query(request, factory)

    assert result.ok
    assert result.warnings == ()
    assert result.data is not None
    assert result.data.validated_arguments == {
        "company_query": "테스트",
        "report_kind": None,
    }
    assert result.data.columns == (
        "company_query",
        "report_kind",
        "company_name",
        "corp_code",
        "stock_code",
        "market",
        "ranking",
        "match_confidence",
    )
    assert result.data.rows[0]["company_name"] == "테스트"
    assert result.data.warnings == source.warnings
    assert result.data.total_rows == 1
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services[0].calls) == 1


def test_search_companies_empty_retains_company_baseline() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "없는 회사"},
        page_size=1,
    )

    result = execute_normalized_excel_query(request, factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns[-1] == "match_confidence"
    assert len(factory.services[0].calls) == 1


def test_search_companies_preserves_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "company source failed",
        retryable=True,
    )
    warning = WarningInfo(
        code=WarningCode.FALLBACK_SOURCE_USED,
        message="fallback failed",
    )
    source = Result[tuple[Company, ...]].failure(
        error,
        warnings=(warning,),
        next_action="retry",
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=source,
    )
    factory = RecordingExcelServiceFactory(responses)
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
        page_size=1,
    )

    result = execute_normalized_excel_query(request, factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.warnings == (warning,)
    assert result.next_action == "retry"
    assert len(factory.services[0].calls) == 1
