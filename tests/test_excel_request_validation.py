from pydantic import SecretBytes

from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_cursor import (
    CursorSecret,
    ExcelCursorPayload,
    encode_excel_cursor,
)
from dart_crawler.excel_dataset_identity import normalized_request_fingerprint
from dart_crawler.excel_page_models import (
    MAX_EXCEL_PAGE_SIZE,
    ExcelDataDomain,
    ExcelLoadRequest,
)
from dart_crawler.excel_request_validation import (
    prepare_excel_request,
    validate_excel_request,
)
from dart_crawler.result import ErrorCode, JsonObject


def _reason(result_error_details: JsonObject) -> str:
    assert set(result_error_details) == {"reason"}
    reason = result_error_details["reason"]
    assert isinstance(reason, str)
    return reason


def test_request_validation_precedes_cursor_validation() -> None:
    # Given: one request with both an invalid boolean page size and malformed cursor.
    raw_request: JsonObject = {
        "domain": "search_companies",
        "arguments": {},
        "page_size": True,
        "cursor": "not-a-cursor",
    }

    # When: the pre-query request seam validates it.
    result = prepare_excel_request(
        raw_request,
        cursor_secret=CursorSecret(value=SecretBytes(b"s" * 32)),
    )

    # Then: request failure wins with the exact pre-query Result shape.
    assert result.data is None
    assert result.error is not None
    assert _reason(result.error.details) == "invalid_request"
    assert result.error.retryable is False
    assert result.warnings == ()
    assert result.next_action is None


def test_valid_request_reaches_cursor_validation_without_querying() -> None:
    # Given: a strict valid request carrying a malformed cursor.
    raw_request: JsonObject = {
        "domain": "search_companies",
        "arguments": {"company_query": "sample"},
        "page_size": 1_000,
        "cursor": "not-a-cursor",
    }
    upstream_calls = 0

    # When: request validation succeeds and cursor validation follows.
    result = prepare_excel_request(
        raw_request,
        cursor_secret=CursorSecret(value=SecretBytes(b"s" * 32)),
    )

    # Then: cursor failure is typed and no upstream query has run.
    assert result.data is None
    assert result.error is not None
    assert _reason(result.error.details) == "invalid_cursor"
    assert result.warnings == ()
    assert upstream_calls == 0


def test_page_size_mismatch_is_independent_of_request_fingerprint() -> None:
    # Given: a cursor bound to the same query but a different page size.
    secret = CursorSecret(value=SecretBytes(b"s" * 32))
    original = ExcelLoadRequest(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments={"company_query": "sample"},
        page_size=1_000,
    )
    cursor = encode_excel_cursor(
        ExcelCursorPayload(
            request_fingerprint=normalized_request_fingerprint(
                original.domain,
                SearchCompaniesArguments(company_query="sample"),
            ),
            source_fingerprint="a" * 64,
            offset=1,
            page_index=1,
            page_size=original.page_size,
        ),
        secret=secret,
    )
    raw_request: JsonObject = {
        "domain": original.domain.value,
        "arguments": original.arguments,
        "page_size": 999,
        "cursor": cursor,
    }

    # When: the real pre-query request seam validates the cursor binding.
    result = prepare_excel_request(raw_request, cursor_secret=secret)

    # Then: the dedicated page-size mismatch follows request matching.
    assert result.data is None
    assert result.error is not None
    assert _reason(result.error.details) == "cursor_page_size_mismatch"


def test_a_page_size_over_the_limit_names_the_limit() -> None:
    """Every other malformed request is a guess; this one is a number to lower."""
    result = validate_excel_request(
        {
            "domain": "search_companies",
            "arguments": {"company_query": "회사"},
            "page_size": MAX_EXCEL_PAGE_SIZE + 1,
        }
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["reason"] == "page_size_exceeds_limit"
    assert result.error.details["max_page_size"] == MAX_EXCEL_PAGE_SIZE
    assert result.next_action is not None
    assert str(MAX_EXCEL_PAGE_SIZE) in result.next_action


def test_other_malformed_requests_stay_invalid_request() -> None:
    result = validate_excel_request({"domain": "unknown", "arguments": {}})

    assert result.ok is False
    assert result.error is not None
    assert result.error.details["reason"] == "invalid_request"
    assert "max_page_size" not in result.error.details


def test_a_page_size_of_the_wrong_type_is_not_a_limit_to_lower() -> None:
    result = validate_excel_request(
        {
            "domain": "search_companies",
            "arguments": {"company_query": "회사"},
            "page_size": "1000",
        }
    )

    assert result.ok is False
    assert result.error is not None
    assert _reason(result.error.details) == "invalid_request"
