from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr

from dart_crawler.crawler_service import CrawlerService
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
from dart_crawler.http_client import HttpClient
from dart_crawler.query_limits import QueryPolicy
from dart_crawler.result import Result
from dart_crawler.section_models import ReportSectionData, ReportSectionList


class ExcelQueryService(Protocol):
    def search_companies(
        self,
        company_query: str,
        report_kind: ReportKind | str | None,
    ) -> Result[tuple[Company, ...]]: ...

    def list_report_filings(
        self,
        corp_code: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Filing, ...]]: ...

    def list_report_attachments(
        self,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]: ...

    def list_report_sections(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[ReportSectionList]: ...

    def get_report_sections(
        self,
        rcept_no: str,
        attachment_id: str,
        section_ids: tuple[str, ...] = (),
        section_kinds: tuple[str, ...] = (),
    ) -> Result[ReportSectionData]: ...

    def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        fs_div: str,
    ) -> Result[FinancialStatementData]: ...

    def get_major_accounts(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
    ) -> Result[MajorAccountData]: ...

    def get_financial_indicators(
        self,
        corp_codes: tuple[str, ...],
        bsns_year: int,
        reprt_code: str,
        idx_cl_code: str,
    ) -> Result[FinancialIndicatorData]: ...

    def get_report_topics(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        topics: tuple[str, ...],
    ) -> Result[ReportTopicData]: ...

    def get_company_profile(
        self,
        corp_code: str,
    ) -> Result[CompanyProfileData]: ...

    def get_ownership_reports(
        self,
        corp_code: str,
        report_type: str,
        bgn_de: str = "",
        end_de: str = "",
    ) -> Result[OwnershipReportData]: ...

    def get_material_events(
        self,
        corp_code: str,
        event_types: tuple[str, ...],
        bgn_de: str,
        end_de: str,
    ) -> Result[MaterialEventData]: ...

    def get_registration_statements(
        self,
        corp_code: str,
        stmt_type: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[RegistrationStatementData]: ...


class ExcelQueryServiceFactory(Protocol):
    def create(self, policy: QueryPolicy) -> ExcelQueryService: ...


@dataclass(frozen=True, slots=True)
class CrawlerServiceFactory:
    api_key: SecretStr
    http_client: HttpClient

    def create(self, policy: QueryPolicy) -> ExcelQueryService:
        return CrawlerService(
            self.api_key,
            self.http_client,
            limits=policy,
        )
