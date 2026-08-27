import json
from dataclasses import replace

import httpx2
import pytest
from pydantic import SecretStr

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_page_models import (
    EXCEL_PAGE_BUDGET_BYTES,
)
from dart_crawler.excel_query_service import ExcelQueryServiceFactory
from dart_crawler.http_client import HttpClient
from dart_crawler.mcp_wire import (
    WIRE_REQUEST_ID,
    WireProfile,
)
from dart_crawler.remote_server import build_app
from dart_crawler.result import JsonObject, Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.remote_excel_wire_support import (
    MCP_PATH,
    oracle_body,
    page_request_body,
    page_request_headers,
    response_page_result,
)


def _companies() -> tuple[Company, ...]:
    escaped = '한글 "quote" \\ slash\n{"nested":[1,{"key":"값"}]}'
    return tuple(
        Company(
            company_name=f"{index}:{escaped}:{'x' * 899_900}",
            corp_code="00123456",
            stock_code="123456",
            market=Market.KOSPI,
            ranking=index + 1,
            match_confidence=MatchConfidence.EXACT,
        )
        for index in range(2)
    )


def _request(cursor: str | None = None) -> JsonObject:
    return {
        "domain": "search_companies",
        "arguments": {"company_query": "한글"},
        "page_size": 4,
        "cursor": cursor,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("profile", list(WireProfile))
async def test_size_shrunk_actual_traversal_equals_wire_oracle(
    monkeypatch: pytest.MonkeyPatch,
    profile: WireProfile,
) -> None:
    # Given: two atomic rows where one fits but both exceed completed wire.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success(_companies()),
    )
    factory = RecordingExcelServiceFactory(responses)

    def build_factory(
        api_key: SecretStr,
        http_client: HttpClient,
    ) -> ExcelQueryServiceFactory:
        del api_key, http_client
        return factory

    monkeypatch.setattr(
        "dart_crawler.remote_server._excel_page_factory",
        build_factory,
    )
    app = build_app()
    request = _request()
    page_table: list[tuple[int, int, int, bool]] = []

    # When: only cursor changes across actual JSON Streamable HTTP calls.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        while True:
            response = await client.post(
                MCP_PATH,
                content=page_request_body(profile, request),
                headers=page_request_headers(profile),
            )
            result = response_page_result(response)
            page = result.data
            assert page is not None
            assert response.content == oracle_body(result, profile)
            assert len(response.content) < EXCEL_PAGE_BUDGET_BYTES
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

    # Then: every atomic row is one page, terminal cursor is null, and calls are 1:1.
    assert len(json.dumps(WIRE_REQUEST_ID, separators=(",", ":")).encode()) == 1_024
    assert page_table == [
        (0, 0, 1, False),
        (1, 1, 1, True),
    ]
    assert len(factory.services) == 2
    assert all(len(service.calls) == 1 for service in factory.services)
