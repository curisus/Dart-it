from __future__ import annotations

from typing import Final, Protocol

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from dart_crawler.excel_export_result import Result, export_warning_from_core
from dart_crawler.excel_query_export_models import (
    ExcelExportResult,
    PreparedExcelExportRequest,
    prepare_excel_export_request,
)
from dart_crawler.result import JsonValue

_DESCRIPTION: Final = (
    "Execute one normalized query and publish the complete result as a "
    "validated local XLSX workbook."
)


class LocalExcelExportRunner(Protocol):
    def __call__(
        self,
        request: PreparedExcelExportRequest,
        ctx: Context,
        /,
    ) -> Result[ExcelExportResult]: ...


def register_local_excel_export_tool(
    mcp: MCPServer,
    runner: LocalExcelExportRunner,
) -> None:
    @mcp.tool(description=_DESCRIPTION)
    def export_query_excel(
        request: JsonValue = None,
        *,
        ctx: Context,
    ) -> Result[ExcelExportResult]:
        prepared = prepare_excel_export_request(request)
        if prepared.data is None:
            if prepared.error is None:
                return Result[ExcelExportResult].model_validate(prepared)
            return Result[ExcelExportResult].failure(
                prepared.error,
                warnings=tuple(
                    export_warning_from_core(warning)
                    for warning in prepared.warnings
                ),
                next_action=prepared.next_action,
            )
        return runner(prepared.data, ctx)

    _ = export_query_excel
