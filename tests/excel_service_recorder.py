from __future__ import annotations

from dataclasses import dataclass

from dart_crawler.domain import Attachment, Company, Filing, ReportKind
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
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.result import JsonObject, Result
from dart_crawler.section_models import ReportSectionData, ReportSectionList
from tests.excel_service_responses import ExcelServiceResponses


@dataclass(frozen=True, slots=True)
class RecordedServiceCall:
    domain: ExcelDataDomain
    arguments: JsonObject


class RecordingExcelQueryService:
    def __init__(self, responses: ExcelServiceResponses) -> None:
        self.responses = responses
        self.calls: list[RecordedServiceCall] = []

    def search_companies(
        self,
        company_query: str,
        report_kind: ReportKind | str | None,
    ) -> Result[tuple[Company, ...]]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.SEARCH_COMPANIES,
                {"company_query": company_query, "report_kind": report_kind},
            )
        )
        return self.responses.search_companies

    def list_report_filings(
        self,
        corp_code: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Filing, ...]]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.LIST_REPORT_FILINGS,
                {"corp_code": corp_code, "report_kind": report_kind},
            )
        )
        return self.responses.list_report_filings

    def list_report_attachments(
        self,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
                {"rcept_no": rcept_no},
            )
        )
        return self.responses.list_report_attachments

    def list_report_sections(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[ReportSectionList]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.LIST_REPORT_SECTIONS,
                {"rcept_no": rcept_no, "attachment_id": attachment_id},
            )
        )
        return self.responses.list_report_sections

    def get_report_sections(
        self,
        rcept_no: str,
        attachment_id: str,
        section_ids: tuple[str, ...] = (),
        section_kinds: tuple[str, ...] = (),
    ) -> Result[ReportSectionData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_REPORT_SECTIONS,
                {
                    "rcept_no": rcept_no,
                    "attachment_id": attachment_id,
                    "section_ids": list(section_ids),
                    "section_kinds": list(section_kinds),
                },
            )
        )
        return self.responses.get_report_sections

    def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        fs_div: str,
    ) -> Result[FinancialStatementData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
                {
                    "corp_code": corp_code,
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                    "fs_div": fs_div,
                },
            )
        )
        return self.responses.get_financial_statements

    def get_major_accounts(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
    ) -> Result[MajorAccountData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_MAJOR_ACCOUNTS,
                {
                    "corp_codes": list(corp_codes),
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                },
            )
        )
        return self.responses.get_major_accounts

    def get_financial_indicators(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
        idx_cl_code: str,
    ) -> Result[FinancialIndicatorData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_FINANCIAL_INDICATORS,
                {
                    "corp_codes": list(corp_codes),
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                    "idx_cl_code": idx_cl_code,
                },
            )
        )
        return self.responses.get_financial_indicators

    def get_report_topics(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        topics: tuple[str, ...],
    ) -> Result[ReportTopicData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_REPORT_TOPICS,
                {
                    "corp_code": corp_code,
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                    "topics": list(topics),
                },
            )
        )
        return self.responses.get_report_topics

    def get_company_profile(
        self,
        corp_code: str,
    ) -> Result[CompanyProfileData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_COMPANY_PROFILE,
                {"corp_code": corp_code},
            )
        )
        return self.responses.get_company_profile

    def get_ownership_reports(
        self,
        corp_code: str,
        report_type: str,
        bgn_de: str = "",
        end_de: str = "",
    ) -> Result[OwnershipReportData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_OWNERSHIP_REPORTS,
                {
                    "corp_code": corp_code,
                    "report_type": report_type,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
            )
        )
        return self.responses.get_ownership_reports

    def get_material_events(
        self,
        corp_code: str,
        event_types: tuple[str, ...],
        bgn_de: str,
        end_de: str,
    ) -> Result[MaterialEventData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_MATERIAL_EVENTS,
                {
                    "corp_code": corp_code,
                    "event_types": list(event_types),
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
            )
        )
        return self.responses.get_material_events

    def get_registration_statements(
        self,
        corp_code: str,
        stmt_type: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[RegistrationStatementData]:
        self.calls.append(
            RecordedServiceCall(
                ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
                {
                    "corp_code": corp_code,
                    "stmt_type": stmt_type,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
            )
        )
        return self.responses.get_registration_statements
