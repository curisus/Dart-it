from dataclasses import dataclass

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
from dart_crawler.result import Result
from dart_crawler.section_models import ReportSectionData, ReportSectionList


@dataclass(frozen=True, slots=True)
class ExcelServiceResponses:
    search_companies: Result[tuple[Company, ...]]
    list_report_filings: Result[tuple[Filing, ...]]
    list_report_attachments: Result[tuple[Attachment, ...]]
    list_report_sections: Result[ReportSectionList]
    get_report_sections: Result[ReportSectionData]
    get_financial_statements: Result[FinancialStatementData]
    get_major_accounts: Result[MajorAccountData]
    get_financial_indicators: Result[FinancialIndicatorData]
    get_report_topics: Result[ReportTopicData]
    get_company_profile: Result[CompanyProfileData]
    get_ownership_reports: Result[OwnershipReportData]
    get_material_events: Result[MaterialEventData]
    get_registration_statements: Result[RegistrationStatementData]
