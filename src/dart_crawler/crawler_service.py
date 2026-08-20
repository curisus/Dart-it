"""Stateless orchestration of the four public report operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

from pydantic import SecretStr

from dart_crawler.amount_checker import compare_statement_amounts
from dart_crawler.api_models import DartListRow
from dart_crawler.attachments import AttachmentService
from dart_crawler.company_search import CompanySearchService
from dart_crawler.dart_api import DartApi, FinancialQuery
from dart_crawler.document_model import ParsedDocument
from dart_crawler.document_parser import parse_attachment
from dart_crawler.document_validation import validate_document
from dart_crawler.domain import Attachment, Company, Filing, ReportKind
from dart_crawler.domains.company_profile import (
    CompanyProfileData,
    CompanyProfileService,
)
from dart_crawler.domains.financials import (
    FinancialIndicatorData,
    FinancialsService,
    FinancialStatementData,
    MajorAccountData,
)
from dart_crawler.domains.ownership import OwnershipReportData, OwnershipService
from dart_crawler.domains.report_topics import ReportTopicData, ReportTopicService
from dart_crawler.excel_export import ExcelExportService, ExportContext, ExportedFile
from dart_crawler.filing_service import FilingService
from dart_crawler.http_client import HttpClient
from dart_crawler.markdown_export import MarkdownExportedFile, MarkdownExportService
from dart_crawler.result import (
    ErrorCode,
    ErrorInfo,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from dart_crawler.section_models import (
    ReportSectionData,
    ReportSectionList,
    missing_core_sections,
    returned_cell_count,
    returned_text_char_count,
    select_sections,
    summarize_sections,
)

PARSER_VERSION: Final = "0.1.0"

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    """One parsed attachment with the listing metadata that describes it."""

    document: ParsedDocument
    attachment_title: str
    source_rcept_no: str


class CrawlerService:
    """Build per-request adapters while retaining no user selection state."""

    def __init__(
        self,
        api_key: SecretStr,
        http_client: HttpClient,
        *,
        output_dir: Path | None = None,
    ) -> None:
        self._api = DartApi(http_client, api_key=api_key.get_secret_value())
        # Remote requests have no writable filesystem, so exporting is optional.
        self._output_dir = output_dir

    def search_companies(
        self,
        company_query: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Company, ...]]:
        """Search companies that have the requested report family."""
        return CompanySearchService(self._api).search(company_query, report_kind)

    def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        fs_div: str,
    ) -> Result[FinancialStatementData]:
        """Return every official account row for one company and filing period."""
        return FinancialsService(self._api).full_statements(
            corp_code, bsns_year, reprt_code, fs_div
        )

    def get_major_accounts(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
    ) -> Result[MajorAccountData]:
        """Return DS003 major-account rows for up to ten companies."""
        return FinancialsService(self._api).major_accounts(
            corp_codes, bsns_year, reprt_code
        )

    def get_financial_indicators(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
        idx_cl_code: str,
    ) -> Result[FinancialIndicatorData]:
        """Return one DS003 financial-indicator family for up to ten companies."""
        return FinancialsService(self._api).indicators(
            corp_codes, bsns_year, reprt_code, idx_cl_code
        )

    def get_report_topics(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        topics: tuple[str, ...],
    ) -> Result[ReportTopicData]:
        """Return DS002 regular-report key-information rows for the topics."""
        return ReportTopicService(self._api).get(corp_code, bsns_year, reprt_code, topics)

    def get_company_profile(self, corp_code: str) -> Result[CompanyProfileData]:
        """Return DART DS001 company master data for one corp_code."""
        return CompanyProfileService(self._api).get(corp_code)

    def get_ownership_reports(
        self,
        corp_code: str,
        report_type: str,
        bgn_de: str = "",
        end_de: str = "",
    ) -> Result[OwnershipReportData]:
        """Return DS004 ownership-disclosure rows for one company and report type."""
        return OwnershipService(self._api).get(corp_code, report_type, bgn_de, end_de)

    def list_report_filings(
        self,
        corp_code: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Filing, ...]]:
        """List recent representative filings for one company code."""
        company = self.search_companies(corp_code, report_kind)
        if not company.ok or not company.data:
            return Result.failure(
                company.error
                if company.error is not None
                else _not_found("회사코드에 해당하는 회사를 찾지 못했습니다."),
                warnings=company.warnings,
                next_action="회사코드와 보고서 종류를 확인하세요.",
            )
        return FilingService(self._api).list(
            corp_code,
            company.data[0].company_name,
            report_kind,
        )

    def list_report_attachments(self, rcept_no: str) -> Result[tuple[Attachment, ...]]:
        """List selectable report attachments for one receipt number."""
        return AttachmentService(self._api).list(rcept_no)

    def export_report_excel(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[ExportedFile]:
        """Collect, compare, parse, and export one selected attachment."""
        output_dir = self._output_dir
        if output_dir is None:
            return Result.failure(
                error_info(
                    ErrorCode.CONFIG_ERROR,
                    "출력 폴더가 설정되지 않아 엑셀을 만들 수 없습니다.",
                    retryable=False,
                ),
                next_action="출력 폴더가 설정된 로컬 서버에서 실행하세요.",
            )
        context = self._prepare_export_context(rcept_no, attachment_id)
        if not context.ok or context.data is None:
            return Result.failure(
                context.error
                if context.error is not None
                else _not_found("첨부문서를 준비하지 못했습니다."),
                warnings=context.warnings,
                next_action=context.next_action,
            )
        exported = ExcelExportService(output_dir).export(context.data)
        return _merge_export_warnings(exported, (), "엑셀 생성에 실패했습니다.")

    def export_report_markdown(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[MarkdownExportedFile]:
        """Collect, compare, parse, and render one selected attachment as Markdown."""
        output_dir = self._output_dir
        if output_dir is None:
            return Result.failure(
                error_info(
                    ErrorCode.CONFIG_ERROR,
                    "출력 폴더가 설정되지 않아 마크다운을 만들 수 없습니다.",
                    retryable=False,
                ),
                next_action="출력 폴더가 설정된 로컬 서버에서 실행하세요.",
            )
        context = self._prepare_export_context(rcept_no, attachment_id)
        if not context.ok or context.data is None:
            return Result.failure(
                context.error
                if context.error is not None
                else _not_found("첨부문서를 준비하지 못했습니다."),
                warnings=context.warnings,
                next_action=context.next_action,
            )
        exported = MarkdownExportService(output_dir).export(context.data)
        return _merge_export_warnings(exported, (), "마크다운 생성에 실패했습니다.")

    def _prepare_export_context(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[ExportContext]:
        """Collect, compare, and package one selected attachment for either exporter."""
        disclosure = self._api.find_disclosure(rcept_no)
        if not disclosure.ok or disclosure.data is None:
            return Result.failure(
                disclosure.error
                if disclosure.error is not None
                else _not_found("접수번호 공시를 찾지 못했습니다."),
                next_action="접수번호를 먼저 공시 목록에서 선택하세요.",
            )
        loaded = self._load_parsed_document(rcept_no, attachment_id)
        if not loaded.ok or loaded.data is None:
            return Result.failure(
                loaded.error
                if loaded.error is not None
                else _not_found("첨부문서를 준비하지 못했습니다."),
                warnings=loaded.warnings,
                next_action=loaded.next_action,
            )
        document = loaded.data.document
        comparison_warnings = _comparison_warnings(
            self._api,
            disclosure.data,
            loaded.data.attachment_title,
            document,
        )
        date_warning: tuple[WarningInfo, ...] = ()
        report_date = _report_date(document)
        if report_date is None:
            date_warning = (
                WarningInfo(
                    code=WarningCode.FALLBACK_SOURCE_USED,
                    message="본문 작성일을 찾지 못해 접수일자를 파일명에 사용했습니다.",
                ),
            )
        correction_chain = _correction_chain(self._api, disclosure.data)
        return Result.success(
            ExportContext(
                company_name=disclosure.data.corp_name,
                report_date=report_date,
                report_title=loaded.data.attachment_title,
                receipt_date=disclosure.data.rcept_dt,
                rcept_no=rcept_no,
                source_rcept_no=loaded.data.source_rcept_no,
                attachment_id=attachment_id,
                correction_chain=correction_chain,
                source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                parser_version=PARSER_VERSION,
                document=document,
                comparison_warnings=comparison_warnings,
                collection_warnings=loaded.warnings + date_warning,
            )
        )

    def list_report_sections(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[ReportSectionList]:
        """List the sections of one attachment without returning their content."""
        loaded = self._validated_document(rcept_no, attachment_id)
        if not loaded.ok or loaded.data is None:
            return Result.failure(
                loaded.error
                if loaded.error is not None
                else _not_found("첨부문서를 준비하지 못했습니다."),
                warnings=loaded.warnings,
                next_action=loaded.next_action,
            )
        document = loaded.data.document
        summaries = summarize_sections(document)
        coverage = document.source_coverage
        return Result.success(
            ReportSectionList(
                rcept_no=rcept_no,
                attachment_id=attachment_id,
                report_title=document.report_title,
                source_type=document.source_type,
                source_sha256=document.source_sha256,
                parser_version=PARSER_VERSION,
                coverage_complete=coverage is not None and coverage.complete,
                section_count=len(summaries),
                total_cell_count=sum(summary.cell_count for summary in summaries),
                total_text_char_count=sum(
                    summary.text_char_count for summary in summaries
                ),
                sections=summaries,
            ),
            warnings=loaded.warnings + _core_statement_warnings(document),
        )

    def get_report_sections(
        self,
        rcept_no: str,
        attachment_id: str,
        section_ids: tuple[str, ...] = (),
        section_kinds: tuple[str, ...] = (),
    ) -> Result[ReportSectionData]:
        """Return every block of the sections named by identifier or by kind."""
        loaded = self._validated_document(rcept_no, attachment_id)
        if not loaded.ok or loaded.data is None:
            return Result.failure(
                loaded.error
                if loaded.error is not None
                else _not_found("첨부문서를 준비하지 못했습니다."),
                warnings=loaded.warnings,
                next_action=loaded.next_action,
            )
        document = loaded.data.document
        selected = select_sections(document, section_ids, section_kinds)
        if not selected.ok or selected.data is None:
            return Result.failure(
                selected.error
                if selected.error is not None
                else _not_found("선택한 구역을 찾지 못했습니다."),
                warnings=loaded.warnings,
                next_action=selected.next_action,
            )
        return Result.success(
            ReportSectionData(
                rcept_no=rcept_no,
                attachment_id=attachment_id,
                source_sha256=document.source_sha256,
                parser_version=PARSER_VERSION,
                returned_cell_count=returned_cell_count(selected.data),
                returned_text_char_count=returned_text_char_count(selected.data),
                sections=selected.data,
            ),
            warnings=loaded.warnings + _core_statement_warnings(document),
        )

    def _validated_document(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[LoadedDocument]:
        """Load one attachment and stop before any data that failed its checks.

        ``validate_document`` covers parsing fidelity — source coverage, table
        shape, merge consistency — so its failure means the parse itself cannot
        be trusted. The data tools therefore share the Excel path's hard gate:
        a partial parse is never returned as if it were the source.
        """
        loaded = self._load_parsed_document(rcept_no, attachment_id)
        if not loaded.ok or loaded.data is None:
            return loaded
        validation = validate_document(loaded.data.document)
        if not validation.ok:
            return Result.failure(
                validation.error
                if validation.error is not None
                else error_info(
                    ErrorCode.VALIDATION_FAILED,
                    "원문 구조 검증 결과를 확인할 수 없습니다.",
                    retryable=False,
                ),
                warnings=loaded.warnings,
                next_action=validation.next_action,
            )
        return loaded

    def _load_parsed_document(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[LoadedDocument]:
        """List, read, and parse one selected attachment of a receipt number.

        The envelope carries every warning collected so far on both the success
        and the failure path, so a caller merges ``result.warnings`` instead of
        listing the attachments again. Disclosure metadata is deliberately
        absent: ``find_disclosure`` costs up to hundreds of round trips and only
        the Excel export needs the company name and the receipt date.
        """
        attachment_service = AttachmentService(self._api)
        attachments = attachment_service.list(rcept_no)
        selected_attachment = _selected_attachment(attachments.data, attachment_id)
        listing_succeeded = attachments.ok and attachments.data is not None
        if selected_attachment is None and listing_succeeded:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    (
                        "첨부 식별자가 이 접수번호의 목록에 없습니다. "
                        "list_report_attachments에서 반환된 식별자를 선택하세요."
                    ),
                    retryable=False,
                ),
                warnings=attachments.warnings,
                next_action="list_report_attachments를 다시 호출해 첨부를 선택하세요.",
            )
        read_selection: str | Attachment = (
            selected_attachment
            if selected_attachment is not None
            else attachment_id
        )
        content = attachment_service.read_selected(rcept_no, read_selection)
        if not content.ok or content.data is None:
            return Result.failure(
                content.error
                if content.error is not None
                else _not_found("선택한 첨부문서를 읽지 못했습니다."),
                warnings=attachments.warnings,
                next_action="첨부문서 목록을 다시 조회하세요.",
            )
        document = parse_attachment(content.data, attachment_id)
        if not document.ok or document.data is None:
            return Result.failure(
                document.error
                if document.error is not None
                else _not_found("첨부문서 구조를 해석하지 못했습니다."),
                warnings=attachments.warnings + document.warnings,
                next_action="다른 첨부문서를 선택하거나 DART 구조 변경을 확인하세요.",
            )
        return Result.success(
            LoadedDocument(
                document=document.data,
                attachment_title=(
                    selected_attachment.title
                    if selected_attachment is not None
                    else "DART 보고서"
                ),
                source_rcept_no=(
                    selected_attachment.source_rcept_no
                    if selected_attachment is not None
                    else rcept_no
                ),
            ),
            warnings=attachments.warnings + document.warnings,
        )


def _core_statement_warnings(document: ParsedDocument) -> tuple[WarningInfo, ...]:
    """Warn about absent core statements instead of failing the data tools.

    The Excel path refuses the export outright, but the data contract is to
    return what the source holds, so a report without one of the four core
    statements still succeeds and names what it lacks.
    """
    missing = missing_core_sections(document)
    if not missing:
        return ()
    return (
        WarningInfo(
            code=WarningCode.PARTIAL_COLLECTION,
            message="원문에서 핵심 재무제표를 찾지 못한 채로 구역을 반환했습니다.",
            details={"missing_sections": list(missing)},
        ),
    )


def _selected_attachment(
    attachments: tuple[Attachment, ...] | None, attachment_id: str
) -> Attachment | None:
    if attachments:
        for attachment in attachments:
            if attachment.attachment_id == attachment_id:
                return attachment
    return None


def _comparison_warnings(
    api: DartApi,
    disclosure: DartListRow,
    attachment_title: str,
    document: ParsedDocument,
) -> tuple[WarningInfo, ...]:
    year_match = re.search(r"20\d{2}", disclosure.report_nm)
    if year_match is None:
        return (
            WarningInfo(
                code=WarningCode.COMPARISON_UNAVAILABLE,
                message="사업연도를 판별하지 못해 금액을 비교하지 못했습니다.",
            ),
        )
    fs_div = "CFS" if "연결" in attachment_title else "OFS"
    query = FinancialQuery(
        corp_code=disclosure.corp_code,
        business_year=int(year_match.group()),
        report_code=_report_code(disclosure.report_nm),
        statement_scope=fs_div,
    )
    accounts = api.fetch_financial_accounts(query)
    if not accounts.ok or accounts.data is None:
        return (
            WarningInfo(
                code=WarningCode.COMPARISON_UNAVAILABLE,
                message="공식 전체 계정과목 자료가 없어 금액을 비교하지 못했습니다.",
            ),
        )
    return compare_statement_amounts(document, accounts.data)


def _report_date(document: ParsedDocument) -> str | None:
    texts = (
        block.text
        for section in document.sections
        for block in section.blocks
        if block.text
    )
    for text in texts:
        match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
        if match is not None:
            return (
                f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            )
    return None


def _report_code(report_name: str) -> str:
    if "사업보고서" in report_name or "감사보고서" in report_name:
        return "11011"
    if "반기" in report_name:
        return "11012"
    if "3분기" in report_name or ".09" in report_name:
        return "11014"
    return "11013"


def _correction_chain(api: DartApi, disclosure: DartListRow) -> tuple[str, ...]:
    report_kind = _report_kind(disclosure.report_nm)
    filings = FilingService(api).list(
        disclosure.corp_code,
        disclosure.corp_name,
        report_kind,
    )
    if filings.ok and filings.data is not None:
        for filing in filings.data:
            if disclosure.rcept_no in filing.correction_chain:
                return filing.correction_chain
    return (disclosure.rcept_no,)


def _report_kind(report_name: str) -> ReportKind:
    if "반기" in report_name:
        return ReportKind.HALF_YEAR_REVIEW
    if "분기" in report_name:
        return ReportKind.QUARTERLY_REVIEW
    return ReportKind.AUDIT


def _not_found(message: str) -> ErrorInfo:
    return error_info(ErrorCode.NOT_FOUND, message, retryable=False)


def _merge_export_warnings(
    result: Result[T],
    additional: tuple[WarningInfo, ...],
    fallback_message: str,
) -> Result[T]:
    if result.ok and result.data is not None:
        return Result.success(
            result.data,
            warnings=result.warnings + additional,
            next_action=result.next_action,
        )
    return Result.failure(
        result.error if result.error is not None else _not_found(fallback_message),
        warnings=result.warnings + additional,
        next_action=result.next_action,
    )
