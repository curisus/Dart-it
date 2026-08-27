import json
import logging
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
    MCP_PATH,
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


@pytest.mark.anyio
async def test_each_excel_page_resolves_request_scoped_auth_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: three stable rows and distinct credentials for each page request.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
    credentials = (
        "todo5-direct-secret",
        "todo5-bearer-secret",
        "todo5-query-secret",
    )
    companies = tuple(
        Company(
            company_name=f"테스트 회사 {index}",
            corp_code=f"{index:08d}",
            stock_code=f"{index:06d}",
            market=Market.KOSPI,
            ranking=index,
            match_confidence=MatchConfidence.EXACT,
        )
        for index in range(1, 4)
    )
    responses = replace(
        empty_excel_service_responses(),
        search_companies=Result.success(companies),
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
    targets = (
        RemoteRequest(
            path=f"{MCP_PATH}?key=query-shadow",
            headers=(
                ("X-OpenDART-API-Key", credentials[0]),
                ("Authorization", "Bearer bearer-shadow"),
            ),
        ),
        RemoteRequest(
            path=f"{MCP_PATH}?key=query-shadow",
            headers=(
                ("X-OpenDART-API-Key", "   "),
                ("Authorization", f"Bearer {credentials[1]}"),
            ),
        ),
        RemoteRequest(
            path=(
                f"{MCP_PATH}?key=query-ignored&key=%20{credentials[2]}%20"
            ),
        ),
    )

    # When: the client follows next_cursor and changes only cursor/auth transport.
    caplog.set_level(logging.DEBUG)
    cursor: str | None = None
    pages: list[ExcelPage] = []
    envelopes: list[JsonObject] = []
    for target in targets:
        request: JsonObject = {
            "domain": "search_companies",
            "arguments": {"company_query": "테스트 회사"},
            "page_size": 1,
            "cursor": cursor,
        }
        envelope = await call_tool_envelope(
            "load_excel_page",
            {"request": request},
            target,
        )
        result = Result[ExcelPage].model_validate(envelope)
        assert result.ok is True
        page = result.data
        assert page is not None
        envelopes.append(envelope)
        pages.append(page)
        cursor = page.next_cursor

    alternate_credential = "todo5-alternate-secret"
    alternate_envelope = await call_tool_envelope(
        "load_excel_page",
        {
            "request": {
                "domain": "search_companies",
                "arguments": {"company_query": "테스트 회사"},
                "page_size": 1,
                "cursor": None,
            }
        },
        RemoteRequest(
            headers=(("X-OpenDART-API-Key", alternate_credential),)
        ),
    )
    alternate_result = Result[ExcelPage].model_validate(alternate_envelope)
    assert alternate_result.ok is True
    alternate_page = alternate_result.data
    assert alternate_page is not None

    missing_envelope = await call_tool_envelope(
        "load_excel_page",
        {
            "request": {
                "domain": "search_companies",
                "arguments": {"company_query": "테스트 회사"},
                "page_size": 1,
                "cursor": None,
            }
        },
    )
    missing = Result[ExcelPage].model_validate(missing_envelope)

    # Then: precedence, complete traversal, no-key failure, and redaction are exact.
    assert captured_keys == [*credentials, alternate_credential]
    assert [page.page_index for page in pages] == [0, 1, 2]
    assert [page.offset for page in pages] == [0, 1, 2]
    assert [page.returned_rows for page in pages] == [1, 1, 1]
    assert [page.total_rows for page in pages] == [3, 3, 3]
    assert [page.rows[0]["company_name"] for page in pages] == [
        "테스트 회사 1",
        "테스트 회사 2",
        "테스트 회사 3",
    ]
    assert pages[0].next_cursor is not None
    assert pages[1].next_cursor is not None
    assert pages[2].next_cursor is None
    assert alternate_page.request_fingerprint == pages[0].request_fingerprint
    assert alternate_page.source_fingerprint == pages[0].source_fingerprint
    assert alternate_page.dataset_id == pages[0].dataset_id
    assert alternate_page.next_cursor == pages[0].next_cursor
    assert len(factory.services) == 4
    assert all(len(service.calls) == 1 for service in factory.services)
    assert missing.data is None
    assert missing.error is not None
    assert missing.error.code.value == "CONFIG_ERROR"
    assert len(factory.services) == 4

    visible_output = json.dumps(
        [*envelopes, alternate_envelope, missing_envelope],
        ensure_ascii=False,
        sort_keys=True,
    ) + caplog.text
    sensitive_values = (
        *credentials,
        alternate_credential,
        "bearer-shadow",
        "query-shadow",
        "query-ignored",
        "s" * 32,
    )
    for sensitive_value in sensitive_values:
        assert sensitive_value not in visible_output
    assert "?key=" not in caplog.text
