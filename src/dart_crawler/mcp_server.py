"""MCP stdio server exposing the four Dart-Crawler tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from mcp.server import MCPServer

from dart_crawler.crawler_service import CrawlerService
from dart_crawler.domain import Attachment, Company, Filing
from dart_crawler.excel_export import ExportedFile
from dart_crawler.http_client import HttpxClient
from dart_crawler.result import ErrorCode, ErrorInfo, Result, error_info
from dart_crawler.settings import AppSettings, load_settings

mcp = MCPServer("dart_crawler", version="0.1.0")
T = TypeVar("T")


@mcp.tool()
def search_companies(
    company_query: str,
    report_kind: str,
) -> Result[tuple[Company, ...]]:
    """Search up to five companies with the requested report family."""
    return _with_service(
        lambda service: service.search_companies(company_query, report_kind)
    )


@mcp.tool()
def list_report_filings(
    corp_code: str,
    report_kind: str,
) -> Result[tuple[Filing, ...]]:
    """List recent five-year representative filings."""
    return _with_service(
        lambda service: service.list_report_filings(corp_code, report_kind)
    )


@mcp.tool()
def list_report_attachments(rcept_no: str) -> Result[tuple[Attachment, ...]]:
    """List selectable separate and consolidated report attachments."""
    return _with_service(lambda service: service.list_report_attachments(rcept_no))


@mcp.tool()
def export_report_excel(rcept_no: str, attachment_id: str) -> Result[ExportedFile]:
    """Create or reuse the selected report workbook."""
    return _with_service(
        lambda service: service.export_report_excel(rcept_no, attachment_id)
    )


def _with_service(operation: Callable[[CrawlerService], Result[T]]) -> Result[T]:
    settings = load_settings()
    if not settings.ok or settings.data is None:
        return Result.failure(
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
        return operation(CrawlerService(settings, http_client))


def _configuration_error() -> ErrorInfo:
    return error_info(
        ErrorCode.CONFIG_ERROR,
        "서버 설정을 확인할 수 없습니다.",
        retryable=False,
    )


def main() -> None:
    """Run the server over stdio for Claude Code and Codex."""
    mcp.run(transport="stdio")
