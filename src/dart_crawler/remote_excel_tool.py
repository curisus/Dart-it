from collections.abc import Callable
from typing import Annotated, Final

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp_types import CallToolResult

from dart_crawler.excel_page_models import ExcelPage
from dart_crawler.mcp_wire import excel_result_to_call_tool_result
from dart_crawler.result import JsonValue, Result

_LOAD_EXCEL_PAGE_DESCRIPTION: Final = (
    "Load one full-data Excel-oriented JSON page. After every successful call, "
    "while next_cursor is non-null, immediately call load_excel_page again with "
    "identical domain, arguments, and page_size, replacing only cursor; append "
    "the returned rows and stop when next_cursor is null. page_size is the "
    "requested maximum; the actual returned row count can shrink to keep the "
    "completed response below the response budget."
)

type RemoteExcelPageRunner = Callable[[JsonValue, Context], Result[ExcelPage]]


def register_remote_excel_tool(
    mcp: MCPServer,
    runner: RemoteExcelPageRunner,
) -> None:
    @mcp.tool(description=_LOAD_EXCEL_PAGE_DESCRIPTION)
    def load_excel_page(
        request: JsonValue = None,
        *,
        ctx: Context,
    ) -> Annotated[CallToolResult, Result[ExcelPage]]:
        return excel_result_to_call_tool_result(runner(request, ctx))
