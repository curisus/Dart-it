import pytest
from mcp_types import ListToolsResult

from dart_crawler.mcp_server import mcp as local_mcp
from dart_crawler.remote_server import create_remote_server
from tests.remote_server_test_support import (
    MCP_PATH,
    RCEPT_NO,
    call_tool_envelope,
    json_object,
    post_jsonrpc,
    request,
)


@pytest.mark.anyio
async def test_remote_server_exposes_exactly_the_fourteen_data_tools() -> None:
    listed = await create_remote_server().list_tools()
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

    assert names == query_tools | {"load_excel_page"}
    assert len(names) == 14
    assert "export_report_excel" not in names
    assert "export_query_excel" not in names


@pytest.mark.anyio
async def test_local_surface_is_the_remote_surface_plus_the_export_group() -> None:
    remote = {tool.name: tool for tool in await create_remote_server().list_tools()}
    local = {tool.name: tool for tool in await local_mcp.list_tools()}
    shared_remote = {name: tool for name, tool in remote.items() if name in local}

    assert set(local) == set(shared_remote) | {
        "export_query_excel",
        "export_report_excel",
        "export_report_markdown",
    }
    assert "load_excel_page" not in local
    for name, remote_tool in shared_remote.items():
        assert local[name].description == remote_tool.description
        assert local[name].input_schema == remote_tool.input_schema


@pytest.mark.anyio
async def test_search_report_kind_is_optional_on_local_and_remote_surfaces() -> None:
    local = {tool.name: tool for tool in await local_mcp.list_tools()}
    remote = {tool.name: tool for tool in await create_remote_server().list_tools()}

    for tool in (local["search_companies"], remote["search_companies"]):
        assert "report_kind" not in tool.input_schema.get("required", [])
        assert tool.input_schema["properties"]["report_kind"]["anyOf"] == [
            {"type": "string"},
            {"type": "null"},
        ]


@pytest.mark.anyio
async def test_get_on_the_mcp_path_is_refused_instead_of_opening_a_stream() -> None:
    response = await request("GET", MCP_PATH)

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["DELETE", "OPTIONS", "PUT", "HEAD"])
async def test_every_other_method_on_the_mcp_path_advertises_post_only(
    method: str,
) -> None:
    response = await request(method, MCP_PATH)

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.anyio
async def test_the_method_guard_leaves_other_paths_to_the_router() -> None:
    response = await request("GET", "/not-the-mcp-path")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_tools_list_over_http_needs_no_api_key() -> None:
    listed = ListToolsResult.model_validate(await post_jsonrpc("tools/list", {}))

    assert {tool.name for tool in listed.tools} == {
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
        "load_excel_page",
    }
    selection_tool = next(
        tool for tool in listed.tools if tool.name == "get_report_sections"
    )
    assert set(selection_tool.input_schema["properties"]) == {
        "rcept_no",
        "attachment_id",
        "section_ids",
        "section_kinds",
    }
    registration_tool = next(
        tool for tool in listed.tools if tool.name == "get_registration_statements"
    )
    assert set(registration_tool.input_schema["properties"]) == {
        "corp_code",
        "stmt_type",
        "bgn_de",
        "end_de",
    }
    assert registration_tool.description is not None
    assert all(
        stmt_type in registration_tool.description
        for stmt_type in (
            "equity_securities",
            "debt_securities",
            "depositary_receipts",
            "merger",
            "stock_exchange_transfer",
            "division",
        )
    )


@pytest.mark.anyio
async def test_tools_call_without_key_header_returns_config_error_envelope() -> None:
    envelope = await call_tool_envelope(
        "list_report_attachments",
        {"rcept_no": RCEPT_NO},
    )
    error = json_object(envelope["error"])
    next_action = envelope["next_action"]

    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert error["code"] == "CONFIG_ERROR"
    assert error["retryable"] is False
    assert isinstance(next_action, str)
    assert "X-OpenDART-API-Key" in next_action
