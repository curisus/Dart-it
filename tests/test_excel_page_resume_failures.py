from dataclasses import replace

import pytest
from pydantic import SecretBytes

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_cursor import (
    CursorSecret,
    ExcelCursorPayload,
    encode_excel_cursor,
)
from dart_crawler.excel_dataset_identity import normalized_request_fingerprint
from dart_crawler.excel_page_loader import execute_excel_page_request
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelPage
from dart_crawler.mcp_wire import measure_excel_result_wire
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    Result,
    WarningCode,
    WarningInfo,
)
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_SECRET = CursorSecret(value=SecretBytes(b"s" * 32))
_REQUEST_FINGERPRINT = normalized_request_fingerprint(
    ExcelDataDomain.SEARCH_COMPANIES,
    SearchCompaniesArguments(company_query="회사"),
)
_RESTART_ACTION = "커서 없이 첫 페이지부터 다시 요청하세요."


def _companies(count: int = 2) -> tuple[Company, ...]:
    return tuple(
        Company(
            company_name=f"회사-{index}",
            corp_code="00123456",
            stock_code="123456",
            market=Market.KOSPI,
            ranking=(index % 5) + 1,
            match_confidence=MatchConfidence.EXACT,
        )
        for index in range(count)
    )


def _factory(
    warnings: tuple[WarningInfo, ...] = (),
    *,
    count: int = 2,
) -> RecordingExcelServiceFactory:
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success(_companies(count), warnings=warnings),
    )
    return RecordingExcelServiceFactory(responses)


def _request(cursor: str | None, *, page_size: int = 1) -> JsonObject:
    return {
        "domain": "search_companies",
        "arguments": {"company_query": "회사"},
        "page_size": page_size,
        "cursor": cursor,
    }


def _cursor(
    *,
    source_fingerprint: str,
    offset: int,
    page_index: int,
    page_size: int = 1,
) -> str:
    return encode_excel_cursor(
        ExcelCursorPayload(
            request_fingerprint=_REQUEST_FINGERPRINT,
            source_fingerprint=source_fingerprint,
            offset=offset,
            page_index=page_index,
            page_size=page_size,
        ),
        secret=_SECRET,
    )


def _assert_postquery_failure(
    result: Result[ExcelPage],
    reason: str,
) -> None:
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.VALIDATION_FAILED
    assert result.error.retryable is False
    assert result.error.details == {"reason": reason}
    assert result.next_action == _RESTART_ACTION


def test_source_change_precedes_position_after_exactly_one_query() -> None:
    # Given: a signed cursor with both a stale source and invalid terminal offset.
    warning = WarningInfo(
        code=WarningCode.FALLBACK_SOURCE_USED,
        message="ordered warning",
    )
    factory = _factory((warning,))
    cursor = _cursor(source_fingerprint="f" * 64, offset=2, page_index=1)

    # When: the resume request executes against the current normalized dataset.
    result = execute_excel_page_request(
        _request(cursor),
        cursor_secret=_SECRET,
        factory=factory,
    )

    # Then: source_changed wins, preserves fitting warnings, and queries only once.
    _assert_postquery_failure(result, "source_changed")
    assert result.warnings == (warning,)
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1


@pytest.mark.parametrize(
    ("offset", "page_index"),
    [
        pytest.param(2, 1, id="no-remaining-data"),
        pytest.param(1, 0, id="zero-resume-index"),
        pytest.param(1, 2, id="more-pages-than-rows"),
    ],
)
def test_invalid_cursor_position_fails_after_one_query(
    offset: int,
    page_index: int,
) -> None:
    # Given: the current source fingerprint and an impossible resume position.
    baseline_factory = _factory()
    baseline = execute_excel_page_request(
        _request(None),
        cursor_secret=_SECRET,
        factory=baseline_factory,
    )
    assert baseline.data is not None
    cursor = _cursor(
        source_fingerprint=baseline.data.source_fingerprint,
        offset=offset,
        page_index=page_index,
    )
    resume_factory = _factory()

    # When: the signed resume cursor is checked against one fresh source query.
    result = execute_excel_page_request(
        _request(cursor),
        cursor_secret=_SECRET,
        factory=resume_factory,
    )

    # Then: cursor_position_invalid is returned after exactly one resume call.
    _assert_postquery_failure(result, "cursor_position_invalid")
    assert resume_factory.policies == [EXCEL_POLICY]
    assert len(resume_factory.services) == 1
    assert len(resume_factory.services[0].calls) == 1


def test_source_change_drops_all_warnings_when_complete_error_wire_overflows() -> None:
    # Given: a stale cursor and one indivisible warning that exceeds full wire.
    warning = WarningInfo(
        code=WarningCode.PARTIAL_COLLECTION,
        message="w" * 1_800_000,
    )
    factory = _factory((warning,))
    cursor = _cursor(source_fingerprint="f" * 64, offset=1, page_index=1)

    # When: the post-query source-change error is sized for every profile.
    result = execute_excel_page_request(
        _request(cursor),
        cursor_secret=_SECRET,
        factory=factory,
    )

    # Then: warnings are dropped all-or-none and the completed wire fits.
    _assert_postquery_failure(result, "source_changed")
    assert result.warnings == ()
    assert measure_excel_result_wire(result).fits_strictly(3_500_000)
    assert len(factory.services[0].calls) == 1


def test_offset_cannot_exceed_page_index_times_requested_maximum() -> None:
    # Given: a matching-source cursor claiming 1,001 rows after one 1,000-row page.
    baseline = execute_excel_page_request(
        _request(None, page_size=1_000),
        cursor_secret=_SECRET,
        factory=_factory(count=1_502),
    )
    assert baseline.data is not None
    cursor = _cursor(
        source_fingerprint=baseline.data.source_fingerprint,
        offset=1_001,
        page_index=1,
        page_size=1_000,
    )
    resume_factory = _factory(count=1_502)

    # When: the impossible signed position is checked after one fresh query.
    result = execute_excel_page_request(
        _request(cursor, page_size=1_000),
        cursor_secret=_SECRET,
        factory=resume_factory,
    )

    # Then: position validation rejects it without performing a second query.
    _assert_postquery_failure(result, "cursor_position_invalid")
    assert resume_factory.policies == [EXCEL_POLICY]
    assert len(resume_factory.services) == 1
    assert len(resume_factory.services[0].calls) == 1
