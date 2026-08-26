from dataclasses import dataclass, field
from typing import Literal

from dart_crawler.excel_company_arguments import (
    GetCompanyProfileArguments,
    ListReportAttachmentsArguments,
    ListReportFilingsArguments,
    SearchCompaniesArguments,
)
from dart_crawler.excel_disclosure_arguments import (
    GetMaterialEventsArguments,
    GetOwnershipReportsArguments,
    GetRegistrationStatementsArguments,
    GetReportTopicsArguments,
)
from dart_crawler.excel_financial_arguments import (
    GetFinancialIndicatorsArguments,
    GetFinancialStatementsArguments,
    GetMajorAccountsArguments,
)
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_report_arguments import (
    GetReportSectionsArguments,
    ListReportSectionsArguments,
)


@dataclass(frozen=True, slots=True)
class SearchCompaniesQuery:
    arguments: SearchCompaniesArguments
    domain: Literal[ExcelDataDomain.SEARCH_COMPANIES] = field(
        default=ExcelDataDomain.SEARCH_COMPANIES,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ListReportFilingsQuery:
    arguments: ListReportFilingsArguments
    domain: Literal[ExcelDataDomain.LIST_REPORT_FILINGS] = field(
        default=ExcelDataDomain.LIST_REPORT_FILINGS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ListReportAttachmentsQuery:
    arguments: ListReportAttachmentsArguments
    domain: Literal[ExcelDataDomain.LIST_REPORT_ATTACHMENTS] = field(
        default=ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ListReportSectionsQuery:
    arguments: ListReportSectionsArguments
    domain: Literal[ExcelDataDomain.LIST_REPORT_SECTIONS] = field(
        default=ExcelDataDomain.LIST_REPORT_SECTIONS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetReportSectionsQuery:
    arguments: GetReportSectionsArguments
    domain: Literal[ExcelDataDomain.GET_REPORT_SECTIONS] = field(
        default=ExcelDataDomain.GET_REPORT_SECTIONS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetFinancialStatementsQuery:
    arguments: GetFinancialStatementsArguments
    domain: Literal[ExcelDataDomain.GET_FINANCIAL_STATEMENTS] = field(
        default=ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetMajorAccountsQuery:
    arguments: GetMajorAccountsArguments
    domain: Literal[ExcelDataDomain.GET_MAJOR_ACCOUNTS] = field(
        default=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetFinancialIndicatorsQuery:
    arguments: GetFinancialIndicatorsArguments
    domain: Literal[ExcelDataDomain.GET_FINANCIAL_INDICATORS] = field(
        default=ExcelDataDomain.GET_FINANCIAL_INDICATORS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetReportTopicsQuery:
    arguments: GetReportTopicsArguments
    domain: Literal[ExcelDataDomain.GET_REPORT_TOPICS] = field(
        default=ExcelDataDomain.GET_REPORT_TOPICS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetCompanyProfileQuery:
    arguments: GetCompanyProfileArguments
    domain: Literal[ExcelDataDomain.GET_COMPANY_PROFILE] = field(
        default=ExcelDataDomain.GET_COMPANY_PROFILE,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetOwnershipReportsQuery:
    arguments: GetOwnershipReportsArguments
    domain: Literal[ExcelDataDomain.GET_OWNERSHIP_REPORTS] = field(
        default=ExcelDataDomain.GET_OWNERSHIP_REPORTS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetMaterialEventsQuery:
    arguments: GetMaterialEventsArguments
    domain: Literal[ExcelDataDomain.GET_MATERIAL_EVENTS] = field(
        default=ExcelDataDomain.GET_MATERIAL_EVENTS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class GetRegistrationStatementsQuery:
    arguments: GetRegistrationStatementsArguments
    domain: Literal[ExcelDataDomain.GET_REGISTRATION_STATEMENTS] = field(
        default=ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
        init=False,
    )


type ReportValidatedExcelQuery = (
    SearchCompaniesQuery
    | ListReportFilingsQuery
    | ListReportAttachmentsQuery
    | ListReportSectionsQuery
    | GetReportSectionsQuery
    | GetCompanyProfileQuery
)
type FinancialValidatedExcelQuery = (
    GetFinancialStatementsQuery
    | GetMajorAccountsQuery
    | GetFinancialIndicatorsQuery
)
type DisclosureValidatedExcelQuery = (
    GetReportTopicsQuery
    | GetOwnershipReportsQuery
    | GetMaterialEventsQuery
    | GetRegistrationStatementsQuery
)
type ValidatedExcelQuery = (
    ReportValidatedExcelQuery
    | FinancialValidatedExcelQuery
    | DisclosureValidatedExcelQuery
)
