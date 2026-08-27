"""MCP stdio server: the local superset surface of the tool catalog.

The local surface registers every catalog group — the shared query tools plus
the file-producing export tools. Its API key never leaves this machine: it is
read from settings (environment or .env), not from any request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import SecretStr

from dart_crawler.crawler_service import CrawlerService
from dart_crawler.excel_export_result import (
    Result as ExcelResult,
)
from dart_crawler.excel_export_result import (
    export_warning_from_core,
)
from dart_crawler.excel_query_export import execute_prepared_excel_export
from dart_crawler.excel_query_export_models import (
    ExcelExportResult,
    PreparedExcelExportRequest,
)
from dart_crawler.excel_query_service import (
    CrawlerServiceFactory,
    ExcelQueryServiceFactory,
)
from dart_crawler.excel_query_workbook_plan import (
    ExcelClock,
    ExcelWorkbookOptions,
    SystemExcelClock,
)
from dart_crawler.http_client import HttpClient, HttpxClient
from dart_crawler.local_excel_export_tool import register_local_excel_export_tool
from dart_crawler.query_limits import LOCAL_QUERY_LIMITS
from dart_crawler.result import ErrorCode, ErrorInfo, Result, error_info
from dart_crawler.settings import AppSettings, load_settings
from dart_crawler.tool_catalog import register_export_tools, register_query_tools

T = TypeVar("T")


def _with_service(operation: Callable[[CrawlerService], Result[T]]) -> Result[T]:
    settings = load_settings()
    if not settings.ok or settings.data is None:
        return Result[T].failure(
            settings.error if settings.error is not None else _configuration_error(),
            warnings=settings.warnings,
            next_action=settings.next_action,
        )
    return _run_with_settings(settings.data, operation)


def _run_with_settings(
    settings: AppSettings,
    operation: Callable[[CrawlerService], Result[T]],
) -> Result[T]:
    with HttpxClient() as http_client:
        return operation(
            CrawlerService(
                settings.api_key,
                http_client,
                output_dir=settings.output_dir,
                limits=LOCAL_QUERY_LIMITS,
            )
        )


def _run_ignoring_context(
    ctx: Context,
    operation: Callable[[CrawlerService], Result[T]],
    /,
) -> Result[T]:
    # The stdio surface reads its key from settings, never from the request,
    # so the injected context carries nothing this surface needs.
    del ctx
    return _with_service(operation)


def _configuration_error() -> ErrorInfo:
    return error_info(
        ErrorCode.CONFIG_ERROR,
        "서버 설정을 확인할 수 없습니다.",
        retryable=False,
    )


def _build_excel_export_factory(
    api_key: SecretStr,
    http_client: HttpClient,
) -> ExcelQueryServiceFactory:
    return CrawlerServiceFactory(api_key, http_client)


_excel_export_factory = _build_excel_export_factory
_excel_export_clock: ExcelClock = SystemExcelClock()
_excel_export_options = ExcelWorkbookOptions()


def _run_prepared_excel_export(
    request: PreparedExcelExportRequest,
    ctx: Context,
    /,
) -> ExcelResult[ExcelExportResult]:
    del ctx
    settings = load_settings()
    if not settings.ok or settings.data is None:
        return ExcelResult[ExcelExportResult].failure(
            settings.error if settings.error is not None else _configuration_error(),
            warnings=tuple(
                export_warning_from_core(warning)
                for warning in settings.warnings
            ),
            next_action=settings.next_action,
        )
    with HttpxClient() as http_client:
        return execute_prepared_excel_export(
            request,
            factory=_excel_export_factory(settings.data.api_key, http_client),
            output_root=settings.data.output_dir,
            clock=_excel_export_clock,
            options=_excel_export_options,
        )


mcp = MCPServer("dart_crawler", version="0.1.0")
register_query_tools(mcp, _run_ignoring_context)
register_export_tools(mcp, _run_ignoring_context)
register_local_excel_export_tool(mcp, _run_prepared_excel_export)


def main() -> None:
    """Run the server over stdio for Claude Code and Codex."""
    mcp.run(transport="stdio")
