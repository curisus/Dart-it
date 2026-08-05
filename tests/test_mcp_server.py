from pathlib import Path

import pytest
from mcp_types import CallToolResult

from dart_crawler.mcp_server import mcp


@pytest.mark.anyio
async def test_mcp_registers_four_tools_and_returns_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DART_MCP_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_DART_API_KEY", "test-key")

    listed = await mcp.list_tools()
    names = {tool.name for tool in listed}
    assert names == {
        "search_companies",
        "list_report_filings",
        "list_report_attachments",
        "export_report_excel",
    }

    result = await mcp.call_tool(
        "search_companies",
        {"company_query": "005930", "report_kind": "unsupported"},
    )
    assert isinstance(result, CallToolResult)
    structured_content = result.structured_content
    assert structured_content is not None
    assert structured_content["ok"] is False
    assert structured_content["error"]["code"] == "INVALID_INPUT"
