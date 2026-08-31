from dataclasses import replace

import httpx2
import pytest
from pydantic import SecretStr

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_page_models import EXCEL_PAGE_BUDGET_BYTES
from dart_crawler.excel_query_service import ExcelQueryServiceFactory
from dart_crawler.http_client import HttpClient
from dart_crawler.mcp_wire import WireProfile
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.remote_server import build_app
from dart_crawler.result import JsonObject, Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.remote_excel_wire_support import (
    MCP_PATH,
    page_request_body,
    page_request_headers,
    response_page_result,
)


def _companies() -> tuple[Company, ...]:
    return tuple(
        Company(
            company_name=f"company-{index:04d}",
            corp_code=f"{index:08d}",
            stock_code=f"{index:06d}",
            market=Market.KOSPI,
            ranking=(index % 5) + 1,
            match_confidence=MatchConfidence.EXACT,
        )
        for index in range(2_501)
    )


@pytest.mark.anyio
async def test_actual_asgi_traverses_2501_rows_with_cursor_only_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
    companies = _companies()
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success(companies),
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
    request: JsonObject = {
        "domain": "search_companies",
        "arguments": {"company_query": "company"},
        "page_size": 1_000,
        "cursor": None,
    }
    stable_fields = {
        "domain": request["domain"],
        "arguments": request["arguments"],
        "page_size": request["page_size"],
    }
    page_table: list[tuple[int, int, int, bool]] = []
    loaded_names: list[str] = []
    app = build_app()

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        while True:
            assert {
                "domain": request["domain"],
                "arguments": request["arguments"],
                "page_size": request["page_size"],
            } == stable_fields
            response = await client.post(
                MCP_PATH,
                content=page_request_body(WireProfile.MODERN, request),
                headers=page_request_headers(WireProfile.MODERN),
            )
            result = response_page_result(response)
            page = result.data
            assert page is not None
            assert response.headers["content-type"] == "application/json"
            assert len(response.content) < EXCEL_PAGE_BUDGET_BYTES
            assert page.total_rows == len(companies)
            page_table.append(
                (
                    page.page_index,
                    page.offset,
                    page.returned_rows,
                    page.next_cursor is None,
                )
            )
            loaded_names.extend(str(row["company_name"]) for row in page.rows)
            if page.next_cursor is None:
                break
            request = {**request, "cursor": page.next_cursor}

    assert page_table == [
        (0, 0, 1_000, False),
        (1, 1_000, 1_000, False),
        (2, 2_000, 501, True),
    ]
    assert loaded_names == [company.company_name for company in companies]
    assert len(set(loaded_names)) == len(companies)
    assert sum(row_count for _, _, row_count, _ in page_table) == len(companies)
    assert factory.policies == [EXCEL_POLICY] * 3
    assert len(factory.services) == 3
    assert all(len(service.calls) == 1 for service in factory.services)
