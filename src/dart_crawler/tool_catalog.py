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
from dart_crawler.domains.financials import (
    FinancialIndicatorData,
    FinancialStatementData,
    MajorAccountData,
)
from dart_crawler.domains.report_topics import ReportTopicData
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
    """Register the nine read-only query tools shared by every surface."""

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

    @mcp.tool()
    def get_financial_statements(
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        ctx: Context,
        fs_div: str = "CFS",
    ) -> Result[FinancialStatementData]:
        """Return every official account row of one company for one filing period.

        corp_code comes from search_companies (an 8-digit DART code, never a
        stock ticker). reprt_code selects the filing: 11011 annual, 11012
        half-year, 11013 Q1, 11014 Q3. Data covers fiscal year 2015 onward.
        fs_div selects CFS (consolidated, default) or OFS (separate); a
        company with no consolidated statements returns NOT_FOUND whose
        next_action suggests retrying with fs_div="OFS". Amounts are returned
        verbatim as KRW strings (commas possible) and are never converted.
        """
        return run(
            ctx,
            lambda service: service.get_financial_statements(
                corp_code,
                bsns_year,
                reprt_code,
                fs_div,
            ),
        )

    @mcp.tool()
    def get_major_accounts(
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
        ctx: Context,
    ) -> Result[MajorAccountData]:
        """Return key balance-sheet and income-statement accounts for up to ten companies.

        corp_codes come from search_companies (8-digit DART codes, never
        stock tickers). reprt_code selects the filing: 11011 annual, 11012
        half-year, 11013 Q1, 11014 Q3. Data covers fiscal year 2015 onward.
        Intended for cross-company comparison in one call; full account
        detail for a single company belongs to get_financial_statements.
        Amounts are returned verbatim as KRW strings (commas possible) and
        are never converted.
        """
        return run(
            ctx,
            lambda service: service.get_major_accounts(
                corp_codes,
                bsns_year,
                reprt_code,
            ),
        )

    @mcp.tool()
    def get_financial_indicators(
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
        idx_cl_code: str,
        ctx: Context,
    ) -> Result[FinancialIndicatorData]:
        """Return one financial-indicator family for up to ten companies.

        corp_codes come from search_companies (8-digit DART codes, never
        stock tickers). reprt_code selects the filing: 11011 annual, 11012
        half-year, 11013 Q1, 11014 Q3. Data covers fiscal year 2015 onward.
        idx_cl_code selects the indicator family: M210000 profitability,
        M220000 stability, M230000 growth, M240000 activity. Amounts are
        returned verbatim as KRW strings (commas possible) and are never
        converted.
        """
        return run(
            ctx,
            lambda service: service.get_financial_indicators(
                corp_codes,
                bsns_year,
                reprt_code,
                idx_cl_code,
            ),
        )

    @mcp.tool()
    def get_report_topics(
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        topics: tuple[str, ...],
        ctx: Context,
    ) -> Result[ReportTopicData]:
        """Return OpenDART DS002 regular-report key-information rows for one or more topics.

        corp_code comes from search_companies (an 8-digit DART code, never a
        stock ticker). reprt_code selects the filing: 11011 annual, 11012
        half-year, 11013 Q1, 11014 Q3. Data covers fiscal year 2015 onward.
        Up to ten topics per call; each topic's rows are returned verbatim
        with every source field. Supported topics: audit_opinion (auditor
        name, audit opinion, emphasis-of-matter and key audit matters),
        audit_service_contract (audit fee and service contract),
        non_audit_service_contract (non-audit service contracts with the
        auditor). An unknown topic fails with the full supported topic list
        in its error details.
        """
        return run(
            ctx,
            lambda service: service.get_report_topics(
                corp_code,
                bsns_year,
                reprt_code,
                topics,
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
