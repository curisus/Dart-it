import pytest

from dart_crawler.mcp_server import mcp as local_mcp
from dart_crawler.remote_server import create_remote_server


@pytest.mark.anyio
async def test_remote_surface_exposes_only_the_excel_page_loader() -> None:
    # Given: the independently registered local and remote MCP surfaces.
    remote_tools = {
        tool.name: tool for tool in await create_remote_server().list_tools()
    }
    local_tools = {tool.name: tool for tool in await local_mcp.list_tools()}

    # When: the remote-only Excel page tool is inspected.
    page_tool = remote_tools["load_excel_page"]

    # Then: only the remote count grows and the JSON boundary is one optional field.
    assert len(remote_tools) == 14
    assert len(local_tools) == 16
    assert "load_excel_page" not in local_tools
    assert "export_query_excel" in local_tools
    assert set(page_tool.input_schema["properties"]) == {"request"}
    assert page_tool.input_schema.get("required", []) == []
    assert page_tool.output_schema is not None


@pytest.mark.anyio
async def test_existing_remote_tool_schemas_stay_equal_to_local() -> None:
    # Given: the existing query tools are still shared by both surfaces.
    remote_tools = {
        tool.name: tool for tool in await create_remote_server().list_tools()
    }
    local_tools = {tool.name: tool for tool in await local_mcp.list_tools()}
    shared_names = set(remote_tools) & set(local_tools)

    # When/Then: every pre-existing shared schema remains byte-for-byte equal.
    assert len(shared_names) == 13
    for name in shared_names:
        assert remote_tools[name].input_schema == local_tools[name].input_schema
        assert remote_tools[name].output_schema == local_tools[name].output_schema
