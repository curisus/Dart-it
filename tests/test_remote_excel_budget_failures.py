from typing import Literal

import httpx2
import pytest
from pydantic import SecretStr

from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
)
from dart_crawler.excel_page_models import EXCEL_PAGE_BUDGET_BYTES, ExcelDataDomain
from dart_crawler.excel_query_service import (
    ExcelQueryService,
    ExcelQueryServiceFactory,
)
from dart_crawler.excel_row_normalization import PendingExcelRow
from dart_crawler.excel_validated_queries import ValidatedExcelQuery
from dart_crawler.http_client import HttpClient
from dart_crawler.mcp_wire import WireProfile
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.remote_server import build_app
from dart_crawler.result import ErrorCode, JsonObject, Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.remote_excel_wire_support import (
    MCP_PATH,
    oracle_body,
    page_request_body,
    page_request_headers,
    response_page_result,
)

type BudgetCase = Literal["schema", "row"]


def _overflow_dataset(case: BudgetCase) -> NormalizedExcelDataset:
    column = "c" * 1_800_000 if case == "schema" else "value"
    rows = (
        ()
        if case == "schema"
        else (PendingExcelRow(context=(), source=((column, "x" * 1_800_000),)),)
    )
    normalized = normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.SEARCH_COMPANIES,
            arguments=SearchCompaniesArguments(company_query="budget"),
            context_columns=(),
            source_columns=(column,),
            rows=rows,
            warnings=(),
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.SEARCH_COMPANIES,
                source_rows=len(rows),
                normalized_rows=len(rows),
            ),
        )
    )
    assert normalized.data is not None
    return normalized.data


@pytest.mark.anyio
@pytest.mark.parametrize("profile", list(WireProfile))
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("schema", "dataset_schema_exceeds_page_budget"),
        ("row", "row_exceeds_page_budget"),
    ],
)
async def test_actual_wire_returns_atomic_budget_failure(
    monkeypatch: pytest.MonkeyPatch,
    profile: WireProfile,
    case: BudgetCase,
    reason: str,
) -> None:
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", "s" * 32)
    dataset = _overflow_dataset(case)
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
        "arguments": {"company_query": "budget"},
        "page_size": 1,
        "cursor": None,
    }
    app = build_app()

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

    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.VALIDATION_FAILED
    assert result.error.retryable is False
    assert result.error.details == {"reason": reason}
    assert result.warnings == ()
    assert result.next_action == "전체 결과가 필요하면 export_query_excel을 사용하세요."
    assert response.content == oracle_body(result, profile)
    assert len(response.content) < EXCEL_PAGE_BUDGET_BYTES
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert dispatches == [ExcelDataDomain.SEARCH_COMPANIES]
