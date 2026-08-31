import hashlib
from dataclasses import replace

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_canonical_json import canonical_json_bytes
from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_cursor import fingerprint_excel_request
from dart_crawler.excel_dataset_identity import (
    normalized_request_fingerprint,
)
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import (
    EXCEL_SCHEMA_VERSION,
    ExcelDataDomain,
    ExcelLoadRequest,
)
from dart_crawler.result import JsonObject, Result, WarningCode, WarningInfo
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _company(name: str) -> Company:
    return Company(
        company_name=name,
        corp_code="00123456",
        stock_code="123456",
        market=Market.KOSPI,
        ranking=1,
        match_confidence=MatchConfidence.EXACT,
    )


def _execute(
    request: ExcelLoadRequest,
    name: str = "회사",
    warnings: tuple[WarningInfo, ...] = (),
) -> tuple[str, str, str]:
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success((_company(name),), warnings=warnings),
    )
    result = execute_normalized_excel_query(
        request,
        RecordingExcelServiceFactory(responses),
    )
    assert result.data is not None
    return (
        result.data.request_fingerprint,
        result.data.source_fingerprint,
        result.data.dataset_id,
    )


def test_authoritative_request_fingerprint_has_exact_canonical_payload() -> None:
    arguments = SearchCompaniesArguments(company_query="회사")
    validated_arguments: JsonObject = {
        "company_query": "회사",
        "report_kind": None,
    }
    expected_payload: JsonObject = {
        "schema_version": EXCEL_SCHEMA_VERSION,
        "domain": "search_companies",
        "validated_arguments": validated_arguments,
    }
    expected = hashlib.sha256(canonical_json_bytes(expected_payload)).hexdigest()

    actual = normalized_request_fingerprint(
        ExcelDataDomain.SEARCH_COMPANIES,
        arguments,
    )

    assert actual == expected
    assert len(actual) == 64
    assert "회사" not in actual


def test_dispatcher_uses_authoritative_todo2_fingerprint_seam() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
        page_size=1,
    )
    arguments = SearchCompaniesArguments(company_query="회사")

    dispatched, _source, _dataset = _execute(request)

    assert dispatched == normalized_request_fingerprint(
        ExcelDataDomain.SEARCH_COMPANIES,
        arguments,
    )


def test_page_size_and_cursor_do_not_change_dataset_identities() -> None:
    first = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
        page_size=1,
    )
    second = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사", "report_kind": None},
        page_size=1_000,
        cursor="opaque-cursor-ignored-by-todo2",
    )

    assert _execute(first) == _execute(second)


def test_source_change_updates_only_source_and_dataset_id_for_same_request() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
    )

    first_request, first_source, first_dataset = _execute(request, "첫 회사")
    second_request, second_source, second_dataset = _execute(request, "둘째 회사")

    assert first_request == second_request
    assert first_source != second_source
    assert first_dataset != second_dataset


def test_ordered_warnings_participate_in_source_identity() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
    )
    first = WarningInfo(
        code=WarningCode.FALLBACK_SOURCE_USED,
        message="first",
    )
    second = WarningInfo(
        code=WarningCode.PARTIAL_COLLECTION,
        message="second",
    )

    first_ids = _execute(request, warnings=(first, second))
    second_ids = _execute(request, warnings=(second, first))

    assert first_ids[0] == second_ids[0]
    assert first_ids[1] != second_ids[1]
    assert first_ids[2] != second_ids[2]


def test_legacy_raw_helper_difference_is_explicit_todo3_integration_risk() -> None:
    omitted = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
    )
    explicit = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사", "report_kind": None},
    )
    validated = SearchCompaniesArguments(company_query="회사")

    authoritative = normalized_request_fingerprint(
        ExcelDataDomain.SEARCH_COMPANIES,
        validated,
    )

    assert fingerprint_excel_request(omitted) != fingerprint_excel_request(explicit)
    assert _execute(omitted)[0] == authoritative
    assert _execute(explicit)[0] == authoritative


def test_provenance_is_stable_and_secret_free() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "회사"},
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success((_company("회사"),)),
    )
    result = execute_normalized_excel_query(
        request,
        RecordingExcelServiceFactory(responses),
    )
    assert result.data is not None

    serialized = result.data.provenance.model_dump_json()

    for forbidden in (
        "api_key",
        "authorization",
        "request_id",
        "filesystem",
        "exception",
        "timestamp",
    ):
        assert forbidden not in serialized.casefold()
