from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp_types import CallToolResult

from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.mcp_server import mcp
from dart_crawler.result import Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.local_excel_export_test_support import (
    RecordingClock,
    install_local_export_runtime,
)
from tests.local_excel_mcp_result_support import structured_content


@pytest.mark.anyio
async def test_actual_local_tool_uses_project_output_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    clock = RecordingClock(datetime(2026, 2, 3, tzinfo=UTC))
    output_root = install_local_export_runtime(
        monkeypatch,
        tmp_path,
        factory,
        clock,
        use_default_output=True,
    )

    called = await mcp.call_tool(
        "export_query_excel",
        {
            "request": {
                "domain": "search_companies",
                "arguments": {"company_query": "회사"},
            }
        },
    )

    assert isinstance(called, CallToolResult)
    result = Result[ExcelExportResult].model_validate(structured_content(called))
    assert result.ok is True
    assert result.data is not None
    assert Path(result.data.absolute_path).parent == output_root.resolve()
    assert output_root == tmp_path / "output"
