"""Stateless orchestration of the four public report operations."""

from __future__ import annotations

import re

from dart_crawler.amount_checker import compare_statement_amounts
from dart_crawler.api_models import DartListRow
from dart_crawler.attachments import AttachmentService
from dart_crawler.company_search import CompanySearchService
from dart_crawler.dart_api import DartApi, FinancialQuery
from dart_crawler.document_model import ParsedDocument
from dart_crawler.document_parser import parse_attachment
from dart_crawler.domain import Attachment, Company, Filing, ReportKind
from dart_crawler.excel_export import ExcelExportService, ExportContext, ExportedFile
from dart_crawler.filing_service import FilingService
from dart_crawler.http_client import HttpClient
from dart_crawler.result import (
    ErrorCode,
    ErrorInfo,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from dart_crawler.settings import AppSettings


class CrawlerService:
    """Build per-request adapters while retaining no user selection state."""

    def __init__(self, settings: AppSettings, http_client: HttpClient) -> None:
        self._settings = settings
        self._api = DartApi(http_client, api_key=settings.api_key.get_secret_value())

    def search_companies(
        self,
        company_query: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Company, ...]]:
        """Search companies that have the requested report family."""
        return CompanySearchService(self._api).search(company_query, report_kind)

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
        disclosure = self._api.find_disclosure(rcept_no)
        if not disclosure.ok or disclosure.data is None:
            return Result.failure(
                disclosure.error
                if disclosure.error is not None
                else _not_found("접수번호 공시를 찾지 못했습니다."),
                next_action="접수번호를 먼저 공시 목록에서 선택하세요.",
            )
        attachment_service = AttachmentService(self._api)
        attachments = attachment_service.list(rcept_no)
        selected_title = _selected_title(attachments.data, attachment_id)
        content = attachment_service.read_selected(rcept_no, attachment_id)
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
        comparison_warnings = _comparison_warnings(
            self._api,
            disclosure.data,
            selected_title,
            document.data,
        )
        date_warning: tuple[WarningInfo, ...] = ()
        report_date = _report_date(document.data)
        if report_date is None:
            date_warning = (
                WarningInfo(
                    code=WarningCode.FALLBACK_SOURCE_USED,
                    message="본문 작성일을 찾지 못해 접수일자를 파일명에 사용했습니다.",
                ),
            )
        correction_chain = _correction_chain(self._api, disclosure.data)
        context = ExportContext(
            company_name=disclosure.data.corp_name,
            report_date=report_date,
            report_title=selected_title,
            receipt_date=disclosure.data.rcept_dt,
            rcept_no=rcept_no,
            attachment_id=attachment_id,
            correction_chain=correction_chain,
            source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            parser_version="0.1.0",
            document=document.data,
            comparison_warnings=comparison_warnings,
            collection_warnings=(
                attachments.warnings + document.warnings + date_warning
            ),
        )
        exported = ExcelExportService(self._settings.output_dir).export(context)
        return _merge_warnings(exported, ())


def _selected_title(
    attachments: tuple[Attachment, ...] | None, attachment_id: str
) -> str:
    if attachments:
        for attachment in attachments:
            if attachment.attachment_id == attachment_id:
                return attachment.title
    return "DART 보고서"


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


def _merge_warnings(
    result: Result[ExportedFile],
    additional: tuple[WarningInfo, ...],
) -> Result[ExportedFile]:
    if result.ok and result.data is not None:
        return Result.success(
            result.data,
            warnings=result.warnings + additional,
            next_action=result.next_action,
        )
    return Result.failure(
        result.error
        if result.error is not None
        else _not_found("엑셀 생성에 실패했습니다."),
        warnings=result.warnings + additional,
        next_action=result.next_action,
    )
