from collections.abc import Callable
from pathlib import Path

import pytest
from mcp_types import CallToolResult

from dart_crawler import mcp_server
from dart_crawler.crawler_service import CrawlerService
from dart_crawler.domain import Company, Market, MatchConfidence
from dart_crawler.domains.registration_statements import RegistrationStatementData
from dart_crawler.mcp_server import mcp
from dart_crawler.result import ErrorCode, Result, error_info


@pytest.mark.anyio
async def test_mcp_registers_the_local_superset_and_returns_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DART_MCP_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_DART_API_KEY", "test-key")

    listed = await mcp.list_tools()
    names = {tool.name for tool in listed}
    query_tools = {
        "search_companies",
        "list_report_filings",
        "list_report_attachments",
        "list_report_sections",
        "get_report_sections",
        "get_financial_statements",
        "get_major_accounts",
        "get_financial_indicators",
        "get_report_topics",
        "get_company_profile",
        "get_ownership_reports",
        "get_material_events",
        "get_registration_statements",
    }
    assert names == query_tools | {
        "export_report_excel",
        "export_report_markdown",
    }
    assert len(query_tools) == 13
    assert len(names) == 15

    result = await mcp.call_tool(
        "search_companies",
        {"company_query": "005930", "report_kind": "unsupported"},
    )
    assert isinstance(result, CallToolResult)
    structured_content = result.structured_content
    assert structured_content is not None
    assert structured_content["ok"] is False
    assert structured_content["data"] is None
    assert structured_content["error"] is not None
    assert structured_content["error"]["code"] == "INVALID_INPUT"


def _successful_company_search(
    operation: Callable[[CrawlerService], Result[tuple[Company, ...]]],
) -> Result[tuple[Company, ...]]:
    return Result.success(
        (
            Company(
                company_name="Sample Holdings",
                corp_code="00126380",
                stock_code="005930",
                market=Market.KOSPI,
                ranking=1,
                match_confidence=MatchConfidence.EXACT,
            ),
        )
    )


@pytest.mark.anyio
async def test_mcp_success_has_data_only_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DART_MCP_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_DART_API_KEY", "test-key")
    monkeypatch.setattr(mcp_server, "_with_service", _successful_company_search)

    result = await mcp.call_tool(
        "search_companies",
        {"company_query": "005930", "report_kind": "audit"},
    )

    assert isinstance(result, CallToolResult)
    structured_content = result.structured_content
    assert structured_content is not None
    assert structured_content["ok"] is True
    assert structured_content["data"] is not None
    assert structured_content["error"] is None
    assert structured_content["data"][0]["match_confidence"] == "exact"


@pytest.mark.anyio
async def test_registration_statement_tool_passes_singular_stmt_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DART_MCP_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_DART_API_KEY", "test-key")
    captured: list[str] = []

    def record_registration_call(
        _self: CrawlerService,
        corp_code: str,
        stmt_type: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[RegistrationStatementData]:
        assert corp_code == "00126380"
        assert bgn_de == "20240101"
        assert end_de == "20241231"
        captured.append(stmt_type)
        return Result.failure(
            error_info(ErrorCode.NOT_FOUND, "empty", retryable=False)
        )

    monkeypatch.setattr(
        CrawlerService,
        "get_registration_statements",
        record_registration_call,
    )

    await mcp.call_tool(
        "get_registration_statements",
        {
            "corp_code": "00126380",
            "stmt_type": "debt_securities",
            "bgn_de": "20240101",
            "end_de": "20241231",
        },
    )

    assert captured == ["debt_securities"]
