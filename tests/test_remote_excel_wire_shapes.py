from dataclasses import replace

import httpx2
import pytest
from mcp_types import TextContent
from pydantic import SecretStr

from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.excel_canonical_json import canonical_json_text
from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
)
from dart_crawler.excel_page_models import (
    EXCEL_PAGE_BUDGET_BYTES,
    ExcelDataDomain,
    ExcelPage,
)
from dart_crawler.excel_query_service import (
    ExcelQueryService,
    ExcelQueryServiceFactory,
)
from dart_crawler.excel_row_normalization import (
    ExcelSourceValue,
    PendingExcelRow,
)
from dart_crawler.excel_validated_queries import ValidatedExcelQuery
from dart_crawler.http_client import HttpClient
from dart_crawler.mcp_wire import WireProfile
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.remote_server import build_app
from dart_crawler.result import JsonObject, Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.remote_excel_wire_support import (
    MCP_PATH,
    oracle_body,
    page_request_body,
    page_request_headers,
    response_call_tool_result,
    response_page_result,
)


def _wire_shape_dataset() -> NormalizedExcelDataset:
    long_column = f"긴_열_{'c' * 4_096}"
    escaped = '한글 "quote" \\ slash\nline'
    nested: ExcelSourceValue = {
        "z": 2,
        "a": [1, {"key": "값"}],
    }
    normalized = normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.SEARCH_COMPANIES,
            arguments=SearchCompaniesArguments(company_query="한글"),
            context_columns=(),
            source_columns=(long_column, "nested_json", "escaped"),
            rows=(
                PendingExcelRow(
                    context=(),
                    source=(
                        (long_column, "긴 열 값"),
                        ("nested_json", nested),
                        ("escaped", escaped),
                    ),
                ),
            ),
            warnings=(),
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.SEARCH_COMPANIES,
                source_rows=1,
                normalized_rows=1,
            ),
        )
    )
    assert normalized.data is not None
    return normalized.data


@pytest.mark.anyio
@pytest.mark.parametrize("profile", list(WireProfile))
async def test_actual_wire_preserves_long_columns_escapes_and_canonical_json(
    monkeypatch: pytest.MonkeyPatch,
    profile: WireProfile,
) -> None:
    # Given: a typed normalized dispatch with every required escaping edge shape.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
    dataset = _wire_shape_dataset()
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    dispatches: list[ExcelDataDomain] = []

    def build_factory(
        api_key: SecretStr,
        http_client: HttpClient,
    ) -> ExcelQueryServiceFactory:
        del api_key, http_client
        return factory

    def dispatch(
        query: ValidatedExcelQuery,
        service: ExcelQueryService,
    ) -> Result[NormalizedExcelDataset]:
        del service
        dispatches.append(query.domain)
        return Result.success(dataset)

    monkeypatch.setattr(
        "dart_crawler.remote_server._excel_page_factory",
        build_factory,
    )
    monkeypatch.setattr(
        "dart_crawler.excel_normalized_dispatch._dispatch_validated_query",
        dispatch,
    )
    request: JsonObject = {
        "domain": "search_companies",
        "arguments": {"company_query": "한글"},
        "page_size": 1,
        "cursor": None,
    }
    app = build_app()

    # When: the public tool returns the completed profile-specific body.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.post(
            MCP_PATH,
            content=page_request_body(profile, request),
            headers=page_request_headers(profile),
        )
    result = response_page_result(response)

    # Then: actual and oracle bytes match and normalized shapes remain exact.
    assert response.content == oracle_body(result, profile)
    assert response.headers["content-type"] == "application/json"
    page = result.data
    assert page is not None
    assert len(page.columns[0]) > 4_096
    assert page.rows[0]["nested_json"] == canonical_json_text(
        {"z": 2, "a": [1, {"key": "값"}]}
    )
    assert page.rows[0]["escaped"] == '한글 "quote" \\ slash\nline'
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert dispatches == [ExcelDataDomain.SEARCH_COMPANIES]


@pytest.mark.anyio
@pytest.mark.parametrize("profile", list(WireProfile))
async def test_actual_wire_preserves_successful_upstream_next_action(
    monkeypatch: pytest.MonkeyPatch,
    profile: WireProfile,
) -> None:
    # Given: a real normalized source success with meaningful client guidance.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
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
        "arguments": {"company_query": "action company"},
        "page_size": 1,
        "cursor": None,
    }
    app = build_app()

    # When: the actual ASGI tool call completes for either wire profile.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.post(
            MCP_PATH,
            content=page_request_body(profile, request),
            headers=page_request_headers(profile),
        )
    called = response_call_tool_result(response)
    content = called.content[0]
    assert isinstance(content, TextContent)
    content_result = Result[ExcelPage].model_validate_json(content.text)
    structured_result = Result[ExcelPage].model_validate(called.structured_content)
    expected_body = oracle_body(content_result, profile)

    # Then: both public projections preserve one action and exact wire sizing.
    assert called.is_error is False
    assert response.headers["content-type"] == "application/json"
    assert content_result.ok is True
    assert content_result.data is not None
    assert content_result.error is None
    assert content_result.warnings == ()
    assert content_result.next_action == "meaningful-success-action"
    assert structured_result.next_action == "meaningful-success-action"
    assert structured_result == content_result
    assert response.content == expected_body
    assert len(response.content) < EXCEL_PAGE_BUDGET_BYTES
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1
