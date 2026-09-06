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
from typing import Literal, Protocol, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from dart_crawler.crawler_service import CrawlerService
from dart_crawler.domain import Attachment, Company, Filing
from dart_crawler.domains.company_profile import CompanyProfileData
from dart_crawler.domains.financials import (
    FinancialIndicatorData,
    FinancialStatementData,
    MajorAccountData,
)
from dart_crawler.domains.material_events import MaterialEventData
from dart_crawler.domains.ownership import OwnershipReportData
from dart_crawler.domains.registration_statements import RegistrationStatementData
from dart_crawler.domains.report_topics import ReportTopicData
from dart_crawler.excel_export import ExportedFile
from dart_crawler.markdown_export import MarkdownExportedFile
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
    """Register the thirteen read-only query tools shared by every surface.

    Split into three grouped helpers purely to stay under the mccabe
    complexity limit (each nested ``@mcp.tool()`` definition counts as one
    branch of the enclosing function) — the grouping carries no meaning
    beyond that; every tool is still part of one flat catalog.
    """
    _register_document_tools(mcp, run)
    _register_financial_tools(mcp, run)
    _register_disclosure_tools(mcp, run)
    _register_registration_statement_tools(mcp, run)


def _register_document_tools(mcp: MCPServer, run: ServiceRunner) -> None:
    """Register the filing-discovery and section-content tools."""

    @mcp.tool()
    def search_companies(
        company_query: str,
        ctx: Context,
        report_kind: str | None = None,
    ) -> Result[tuple[Company, ...]]:
        """Search up to five companies, optionally filtered by report family."""
        return run(
            ctx,
            lambda service: service.search_companies(company_query, report_kind),
        )

    @mcp.tool()
    def list_report_filings(
        corp_code: str,
        report_kind: Literal["audit", "half_year_review", "quarterly_review"],
        ctx: Context,
    ) -> Result[tuple[Filing, ...]]:
        """List recent five-year representative filings.

        report_kind selects the report family: audit (감사보고서),
        half_year_review (반기검토보고서), quarterly_review (분기검토보고서).
        """
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

        Note titles are normalized to "주석 N" so they fit a worksheet name;
        the heading field keeps the source line ("28. 재무위험관리") so one note
        can be selected without requesting every note to search them.
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


def _register_financial_tools(mcp: MCPServer, run: ServiceRunner) -> None:
    """Register the DS003 official financial-data tools."""

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


def _register_disclosure_tools(mcp: MCPServer, run: ServiceRunner) -> None:
    """Register the DS002/DS001/DS004/DS005 topic, profile, ownership, and event tools."""

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
        with every source field. OpenDART answers "해당 없음" with one row whose
        fields are all "-", so each topic reports substantive_row_count beside
        row_count and a topic of only such rows counts as empty: all empty is
        NOT_FOUND, some empty is PARTIAL_COLLECTION. Supported topics:
        audit_opinion (auditor
        name, audit opinion, emphasis-of-matter and key audit matters),
        audit_service_contract (audit fee and service contract),
        non_audit_service_contract (non-audit service contracts with the
        auditor); dividend, capital_change, treasury_stock, total_shares
        (shares and capital); largest_shareholder,
        largest_shareholder_change, minority_shareholders (ownership);
        executives, employees, outside_directors (people);
        director_individual_pay, director_total_pay, individual_pay_top5,
        unregistered_executive_pay, director_pay_approved,
        director_pay_by_type (compensation); other_corp_investment,
        debt_securities_issued, commercial_paper_balance,
        short_term_bond_balance, corporate_bond_balance,
        hybrid_securities_balance, contingent_capital_balance (investments
        and debt securities); private_fund_usage, public_fund_usage (fund
        usage). An unknown topic fails with the full supported topic list
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

    @mcp.tool()
    def get_company_profile(
        corp_code: str,
        ctx: Context,
    ) -> Result[CompanyProfileData]:
        """Return OpenDART DS001 company master data for one company.

        corp_code comes from search_companies (an 8-digit DART code, never a
        stock ticker). Fields include the Korean and English company names,
        CEO name, corp_cls (market classification), registration numbers
        (jurir_no business registration, bizr_no corporate registration),
        address, homepage and IR URLs, phone and fax numbers, industry code,
        establishment date, and fiscal year-end month.
        """
        return run(ctx, lambda service: service.get_company_profile(corp_code))

    @mcp.tool()
    def get_ownership_reports(
        corp_code: str,
        report_type: str,
        ctx: Context,
        bgn_de: str = "",
        end_de: str = "",
    ) -> Result[OwnershipReportData]:
        """Return OpenDART DS004 ownership-disclosure rows for one company and report type.

        corp_code comes from search_companies (an 8-digit DART code, never a
        stock ticker). report_type selects the report family: "major_holding"
        for 5%-rule large-holding reports, or "insider_ownership" for
        executives and major shareholders ownership reports. Rows are
        returned verbatim with every source field. A company with no reports
        of the requested type still succeeds, with zero rows and a
        partial-collection warning rather than failing. An unknown
        report_type fails with the supported list in its error details.

        bgn_de/end_de (both optional, YYYYMMDD) narrow the rows to those
        whose receipt date falls within [bgn_de, end_de], inclusive; leave
        either side blank for an open bound. A company with a large report
        history (e.g. a large-cap's insider_ownership rows) MUST narrow this
        range when the response exceeds the row budget — the error's
        next_action says so. The response's total_row_count is the row count
        before this filter narrowed it; returned_row_count is the count
        after filtering, i.e. the number of rows actually in `rows`.
        """
        return run(
            ctx,
            lambda service: service.get_ownership_reports(
                corp_code, report_type, bgn_de, end_de
            ),
        )

    @mcp.tool()
    def get_material_events(
        corp_code: str,
        event_types: tuple[str, ...],
        bgn_de: str,
        end_de: str,
        ctx: Context,
    ) -> Result[MaterialEventData]:
        """Return OpenDART DS005 주요사항보고 rows for one company and one or more event types.

        corp_code comes from search_companies (an 8-digit DART code, never a
        stock ticker). bgn_de/end_de (both YYYYMMDD) are REQUIRED and select
        the receipt-date range, inclusive on both ends — unlike
        get_ownership_reports, DART's own DS005 endpoints demand this range
        rather than answering an unbounded history. Up to ten event_types
        per call; each type's rows are returned verbatim with every source
        field, in request order. Supported event_types, grouped for
        reference (an unknown value fails with the full list in its error
        details' supported_event_types):
        distress — bankruptcy, business_suspension, rehabilitation_filing,
        dissolution, creditor_management_start, creditor_management_stop,
        lawsuit;
        capital — paid_in_capital_increase, free_capital_increase,
        paid_in_and_free_increase, capital_reduction;
        bonds — convertible_bond_issue, bond_with_warrant_issue,
        exchangeable_bond_issue, writedown_contingent_bond_issue,
        stock_related_bond_acquisition, stock_related_bond_transfer;
        treasury stock — treasury_stock_acquisition, treasury_stock_disposal,
        treasury_trust_contract, treasury_trust_cancel;
        restructuring — merger, split_merger, company_split,
        stock_exchange_transfer, business_acquisition, business_transfer,
        asset_transfer_putback_option, tangible_asset_acquisition,
        tangible_asset_transfer, other_corp_stock_acquisition,
        other_corp_stock_transfer;
        overseas listing — overseas_listing_decision, overseas_listing,
        overseas_delisting_decision, overseas_delisting.
        A period with no filings for every requested event type still
        succeeds, with zero rows for each and a partial-collection warning
        naming them — that absence is itself the answer, the same policy
        get_ownership_reports uses for a report type with no history.
        """
        return run(
            ctx,
            lambda service: service.get_material_events(
                corp_code, event_types, bgn_de, end_de
            ),
        )


def _register_registration_statement_tools(
    mcp: MCPServer,
    run: ServiceRunner,
) -> None:
    @mcp.tool()
    def get_registration_statements(
        corp_code: str,
        stmt_type: str,
        bgn_de: str,
        end_de: str,
        ctx: Context,
    ) -> Result[RegistrationStatementData]:
        """Return OpenDART DS006 registration-statement rows for one statement type.

        corp_code comes from search_companies (an 8-digit DART code, never a
        stock ticker). bgn_de/end_de (both YYYYMMDD) are REQUIRED and select
        the receipt-date range, inclusive on both ends. stmt_type selects one
        DS006 statement family: equity_securities, debt_securities,
        depositary_receipts, merger, stock_exchange_transfer, division. Rows are
        returned verbatim with every source field, grouped under OpenDART's
        official group titles. A period with no rows still succeeds with zero
        rows and a partial-collection warning; an unknown stmt_type fails with
        the supported list in its error details.
        """
        return run(
            ctx,
            lambda service: service.get_registration_statements(
                corp_code,
                stmt_type,
                bgn_de,
                end_de,
            ),
        )


def register_export_tools(mcp: MCPServer, run: ServiceRunner) -> None:
    """Register the file-producing tools of the local surface.

    File renderers (xlsx, markdown) need a writable output directory, so this
    group never appears on the remote surface.
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

    @mcp.tool()
    def export_report_markdown(
        rcept_no: str,
        attachment_id: str,
        ctx: Context,
    ) -> Result[MarkdownExportedFile]:
        """Create or reuse a Markdown rendering of the selected report attachment.

        Renders the whole parsed attachment — every statement, note, and text
        section, in source order — into one Markdown file and returns the
        output path. Amounts and text are carried verbatim, never truncated.
        Unlike export_report_excel, a report missing a core financial
        statement still succeeds: the file is written with what the source
        holds, and the response's missing_sections and collection_status
        report what is absent.
        """
        return run(
            ctx,
            lambda service: service.export_report_markdown(rcept_no, attachment_id),
        )
