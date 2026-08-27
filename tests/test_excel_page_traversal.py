from dataclasses import replace

from pydantic import SecretBytes

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_cursor import CursorSecret
from dart_crawler.excel_page_loader import execute_excel_page_request
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import JsonObject, Result, WarningCode, WarningInfo
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_CURSOR_SECRET = CursorSecret(value=SecretBytes(b"s" * 32))


def _companies(count: int) -> tuple[Company, ...]:
    return tuple(
        Company(
            company_name=f"회사-{index:04d}",
            corp_code="00123456",
            stock_code="123456",
            market=Market.KOSPI,
            ranking=(index % 5) + 1,
            match_confidence=MatchConfidence.EXACT,
        )
        for index in range(count)
    )


def test_2501_rows_traverse_without_gaps_or_duplicate_source_calls() -> None:
    # Given: one stable 2,501-row normalized source with one ordered warning.
    companies = _companies(2_501)
    warnings = (
        WarningInfo(
            code=WarningCode.FALLBACK_SOURCE_USED,
            message="ordered warning",
        ),
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success(companies, warnings=warnings),
    )
    factory = RecordingExcelServiceFactory(responses)
    request: JsonObject = {
        "domain": "search_companies",
        "arguments": {"company_query": "회사"},
        "page_size": 1_000,
        "cursor": None,
    }
    names: list[str] = []
    page_table: list[tuple[int, int, int, bool]] = []

    # When: an automatic client changes only cursor until it becomes null.
    while True:
        prior_services = len(factory.services)
        result = execute_excel_page_request(
            request,
            cursor_secret=_CURSOR_SECRET,
            factory=factory,
        )
        assert result.ok is True
        assert result.warnings == ()
        page = result.data
        assert page is not None
        assert page.warnings == warnings
        assert len(factory.services) == prior_services + 1
        assert len(factory.services[-1].calls) == 1
        names.extend(str(row["company_name"]) for row in page.rows)
        page_table.append(
            (
                page.page_index,
                page.offset,
                page.returned_rows,
                page.next_cursor is None,
            )
        )
        if page.next_cursor is None:
            break
        request = {**request, "cursor": page.next_cursor}

    # Then: all rows appear once across 1,000/1,000/501 pages and three queries.
    assert page_table == [
        (0, 0, 1_000, False),
        (1, 1_000, 1_000, False),
        (2, 2_000, 501, True),
    ]
    assert names == [company.company_name for company in companies]
    assert len(names) == len(set(names)) == 2_501
    assert sum(item[2] for item in page_table) == 2_501
    assert factory.policies == [EXCEL_POLICY, EXCEL_POLICY, EXCEL_POLICY]
