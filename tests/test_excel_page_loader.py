from dataclasses import replace

from pydantic import SecretBytes

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_cursor import (
    CursorSecret,
    fingerprint_excel_request,
)
from dart_crawler.excel_dataset_identity import (
    normalized_dataset_id,
    normalized_request_fingerprint,
)
from dart_crawler.excel_page_loader import execute_excel_page_request
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_CURSOR_SECRET = CursorSecret(value=SecretBytes(b"s" * 32))


def _request(company_query: str) -> JsonObject:
    return {
        "domain": "search_companies",
        "arguments": {"company_query": company_query},
        "page_size": 1,
        "cursor": None,
    }


def test_first_page_uses_authoritative_normalized_request_identity() -> None:
    # Given: one full normalized source result and an omitted argument default.
    company = Company(
        company_name="테스트 회사",
        corp_code="00123456",
        stock_code="123456",
        market=Market.KOSPI,
        ranking=1,
        match_confidence=MatchConfidence.EXACT,
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success((company,)),
    )
    factory = RecordingExcelServiceFactory(responses)

    # When: the stateless page executor loads the first page.
    result = execute_excel_page_request(
        _request("테스트 회사"),
        cursor_secret=_CURSOR_SECRET,
        factory=factory,
    )

    # Then: the normalized/default-expanded fingerprint is the cursor identity.
    assert result.ok is True
    assert result.warnings == ()
    assert result.next_action is None
    page = result.data
    assert page is not None
    authoritative = normalized_request_fingerprint(
        ExcelDataDomain.SEARCH_COMPANIES,
        SearchCompaniesArguments(company_query="테스트 회사"),
    )
    raw_request = ExcelLoadRequest.model_validate(_request("테스트 회사"))
    assert page.request_fingerprint == authoritative
    assert page.request_fingerprint != fingerprint_excel_request(raw_request)
    assert page.dataset_id == normalized_dataset_id(
        page.domain,
        page.request_fingerprint,
        page.source_fingerprint,
    )
    assert page.provenance.source_fingerprint == page.source_fingerprint
    assert page.rows[0]["company_name"] == "테스트 회사"
    assert page.total_rows == page.returned_rows == 1
    assert page.offset == page.page_index == 0
    assert page.page_size == 1
    assert page.next_cursor is None
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1


def test_empty_first_page_keeps_stable_columns_and_terminal_metadata() -> None:
    # Given: a successful empty normalized source result.
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    # When: the same executor loads its first and only page.
    result = execute_excel_page_request(
        _request("없는 회사"),
        cursor_secret=_CURSOR_SECRET,
        factory=factory,
    )

    # Then: it returns one terminal empty page after exactly one source call.
    assert result.ok is True
    assert result.warnings == ()
    page = result.data
    assert page is not None
    assert page.columns[-1] == "match_confidence"
    assert page.rows == ()
    assert page.total_rows == page.returned_rows == 0
    assert page.offset == page.page_index == 0
    assert page.next_cursor is None
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1


def test_successful_page_preserves_meaningful_upstream_next_action() -> None:
    # Given: a successful source result with a meaningful client action.
    company = Company(
        company_name="action company",
        corp_code="00123456",
        stock_code="123456",
        market=Market.KOSPI,
        ranking=1,
        match_confidence=MatchConfidence.EXACT,
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success(
            (company,),
            next_action="meaningful-success-action",
        ),
    )
    factory = RecordingExcelServiceFactory(responses)

    # When: the public typed loader selects the successful page.
    result = execute_excel_page_request(
        _request("action company"),
        cursor_secret=_CURSOR_SECRET,
        factory=factory,
    )

    # Then: paging preserves the action without moving warnings outward.
    assert result.ok is True
    assert result.data is not None
    assert result.error is None
    assert result.warnings == ()
    assert result.next_action == "meaningful-success-action"
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1


def test_upstream_failure_is_returned_semantically_unchanged() -> None:
    # Given: the selected source returns an existing typed failure with metadata.
    error = error_info(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "source unavailable",
        retryable=True,
        details={"upstream": "dart"},
    )
    warning = WarningInfo(
        code=WarningCode.FALLBACK_SOURCE_USED,
        message="fallback failed",
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.failure(
            error,
            warnings=(warning,),
            next_action="retry source",
        ),
    )
    factory = RecordingExcelServiceFactory(responses)

    # When: the page executor performs its single normalized dispatch.
    result = execute_excel_page_request(
        _request("회사"),
        cursor_secret=_CURSOR_SECRET,
        factory=factory,
    )

    # Then: no paging wrapper changes the existing error, warnings, or action.
    assert result.data is None
    assert result.error == error
    assert result.warnings == (warning,)
    assert result.next_action == "retry source"
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1
