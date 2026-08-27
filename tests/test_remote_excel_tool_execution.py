from dataclasses import replace

import pytest
from pydantic import SecretStr

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_page_models import ExcelPage
from dart_crawler.excel_query_service import (
    ExcelQueryServiceFactory,
)
from dart_crawler.http_client import HttpClient
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import JsonObject, Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.remote_server_test_support import (
    RemoteRequest,
    call_tool_envelope,
)


@pytest.mark.anyio
async def test_actual_remote_tool_executes_one_normalized_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the actual remote server has a valid cursor secret, key, and source.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
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
    captured_keys: list[str] = []

    def build_factory(
        api_key: SecretStr,
        http_client: HttpClient,
    ) -> ExcelQueryServiceFactory:
        del http_client
        captured_keys.append(api_key.get_secret_value())
        return factory

    monkeypatch.setattr(
        "dart_crawler.remote_server._excel_page_factory",
        build_factory,
        raising=False,
    )
    request: JsonObject = {
        "domain": "search_companies",
        "arguments": {"company_query": "테스트 회사"},
        "page_size": 1,
        "cursor": None,
    }

    # When: tools/call reaches load_excel_page through Streamable HTTP JSON.
    envelope = await call_tool_envelope(
        "load_excel_page",
        {"request": request},
        RemoteRequest(headers=(("X-OpenDART-API-Key", "request-key"),)),
    )

    # Then: it returns the typed page after one factory and one source call.
    result = Result[ExcelPage].model_validate(envelope)
    assert result.ok is True
    assert result.warnings == ()
    page = result.data
    assert page is not None
    assert page.rows[0]["company_name"] == "테스트 회사"
    assert page.next_cursor is None
    assert captured_keys == ["request-key"]
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1
