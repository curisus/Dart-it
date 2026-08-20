"""Single catalog of the MCP tools shared by the local and remote surfaces.

Every tool's name, parameters, and description live here exactly once. A
surface module (``mcp_server`` for stdio, ``remote_server`` for streamable
HTTP) passes its own ``ServiceRunner`` — the only thing the surfaces are
allowed to differ in is where the API key and configuration come from, and
which tool groups they register:

- query tools: both surfaces, identical coverage.
- export tools: local only — a remote request has no writable filesystem.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from dart_crawler.crawler_service import CrawlerService
from dart_crawler.domain import Attachment, Company, Filing
from dart_crawler.excel_export import ExportedFile
from dart_crawler.result import Result
from dart_crawler.section_models import ReportSectionData, ReportSectionList

T = TypeVar("T")


class ServiceRunner(Protocol):
    """Executes one service operation with a surface's own key source.

    The stdio surface reads the key and output directory from settings and
    ignores the request context; the HTTP surface reads the key from the
    request. Both receive the injected ``Context`` so one tool definition
    serves both.
    """

    def __call__(
        self,
        ctx: Context,
        operation: Callable[[CrawlerService], Result[T]],
        /,
    ) -> Result[T]: ...


def register_query_tools(mcp: MCPServer, run: ServiceRunner) -> None:
    """Register the five read-only query tools shared by every surface."""

    @mcp.tool()
    def search_companies(
        company_query: str,
        report_kind: str,
        ctx: Context,
    ) -> Result[tuple[Company, ...]]:
        """Search up to five companies with the requested report family."""
        return run(
            ctx,
            lambda service: service.search_companies(company_query, report_kind),
        )

    @mcp.tool()
    def list_report_filings(
        corp_code: str,
        report_kind: str,
        ctx: Context,
    ) -> Result[tuple[Filing, ...]]:
        """List recent five-year representative filings."""
        return run(
            ctx,
            lambda service: service.list_report_filings(corp_code, report_kind),
        )

    @mcp.tool()
    def list_report_attachments(
        rcept_no: str,
        ctx: Context,
    ) -> Result[tuple[Attachment, ...]]:
        """List selectable separate and consolidated report attachments."""
        return run(
            ctx,
            lambda service: service.list_report_attachments(rcept_no),
        )

    @mcp.tool()
    def list_report_sections(
        rcept_no: str,
        attachment_id: str,
        ctx: Context,
    ) -> Result[ReportSectionList]:
        """List one attachment's sections as a table of contents.

        Each entry carries the section_id, title, kind, and cell count needed to
        choose what to request from get_report_sections, without returning any
        of the section content.
        """
        return run(
            ctx,
            lambda service: service.list_report_sections(rcept_no, attachment_id),
        )

    @mcp.tool()
    def get_report_sections(
        rcept_no: str,
        attachment_id: str,
        ctx: Context,
        section_ids: tuple[str, ...] = (),
        section_kinds: tuple[str, ...] = (),
    ) -> Result[ReportSectionData]:
        """Return the full content of the selected sections of one attachment.

        Select by section_ids from list_report_sections, by section_kinds, or by
        both: the union is returned in source order. section_kinds accepts a
        section kind such as balance_sheet or note, plus the alias "statements"
        for the four core financial statements. At least one selector is
        required, and a selection larger than the response limit is rejected
        rather than truncated.
        """
        return run(
            ctx,
            lambda service: service.get_report_sections(
                rcept_no,
                attachment_id,
                section_ids,
                section_kinds,
            ),
        )


def register_export_tools(mcp: MCPServer, run: ServiceRunner) -> None:
    """Register the file-producing tools of the local surface.

    File renderers (xlsx today, markdown planned) need a writable output
    directory, so this group never appears on the remote surface.
    """

    @mcp.tool()
    def export_report_excel(
        rcept_no: str,
        attachment_id: str,
        ctx: Context,
    ) -> Result[ExportedFile]:
        """Create or reuse the selected report workbook."""
        return run(
            ctx,
            lambda service: service.export_report_excel(rcept_no, attachment_id),
        )
