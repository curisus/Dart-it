from typing import Literal

from pydantic import ValidationError

from dart_crawler.excel_company_arguments import (
    GetCompanyProfileArguments,
    ListReportAttachmentsArguments,
    ListReportFilingsArguments,
    SearchCompaniesArguments,
)
from dart_crawler.excel_contract_errors import excel_failure
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
from dart_crawler.excel_validated_queries import (
    GetCompanyProfileQuery,
    GetFinancialIndicatorsQuery,
    GetFinancialStatementsQuery,
    GetMajorAccountsQuery,
    GetMaterialEventsQuery,
    GetOwnershipReportsQuery,
    GetRegistrationStatementsQuery,
    GetReportSectionsQuery,
    GetReportTopicsQuery,
    ListReportAttachmentsQuery,
    ListReportFilingsQuery,
    ListReportSectionsQuery,
    SearchCompaniesQuery,
    ValidatedExcelQuery,
)
from dart_crawler.result import JsonObject, Result

type ReportDomain = Literal[
    ExcelDataDomain.SEARCH_COMPANIES,
    ExcelDataDomain.LIST_REPORT_FILINGS,
    ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
    ExcelDataDomain.LIST_REPORT_SECTIONS,
    ExcelDataDomain.GET_REPORT_SECTIONS,
    ExcelDataDomain.GET_COMPANY_PROFILE,
]
type FinancialDomain = Literal[
    ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
    ExcelDataDomain.GET_MAJOR_ACCOUNTS,
    ExcelDataDomain.GET_FINANCIAL_INDICATORS,
]
type DisclosureDomain = Literal[
    ExcelDataDomain.GET_REPORT_TOPICS,
    ExcelDataDomain.GET_OWNERSHIP_REPORTS,
    ExcelDataDomain.GET_MATERIAL_EVENTS,
    ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
]


def validate_excel_query(
    domain: ExcelDataDomain,
    arguments: JsonObject,
) -> Result[ValidatedExcelQuery]:
    try:
        query = _validated_query(domain, arguments)
    except ValidationError:
        return excel_failure("invalid_request")
    return Result[ValidatedExcelQuery].success(query)


def _validated_query(
    domain: ExcelDataDomain,
    arguments: JsonObject,
) -> ValidatedExcelQuery:
    match domain:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
        case (
            ExcelDataDomain.SEARCH_COMPANIES
            | ExcelDataDomain.LIST_REPORT_FILINGS
            | ExcelDataDomain.LIST_REPORT_ATTACHMENTS
            | ExcelDataDomain.LIST_REPORT_SECTIONS
            | ExcelDataDomain.GET_REPORT_SECTIONS
            | ExcelDataDomain.GET_COMPANY_PROFILE
        ):
            return _validated_report_query(domain, arguments)
        case (
            ExcelDataDomain.GET_FINANCIAL_STATEMENTS
            | ExcelDataDomain.GET_MAJOR_ACCOUNTS
            | ExcelDataDomain.GET_FINANCIAL_INDICATORS
        ):
            return _validated_financial_query(domain, arguments)
        case (
            ExcelDataDomain.GET_REPORT_TOPICS
            | ExcelDataDomain.GET_OWNERSHIP_REPORTS
            | ExcelDataDomain.GET_MATERIAL_EVENTS
            | ExcelDataDomain.GET_REGISTRATION_STATEMENTS
        ):
            return _validated_disclosure_query(domain, arguments)


def _validated_report_query(
    domain: ReportDomain,
    arguments: JsonObject,
) -> ValidatedExcelQuery:
    match domain:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
        case ExcelDataDomain.SEARCH_COMPANIES:
            return SearchCompaniesQuery(
                SearchCompaniesArguments.model_validate(arguments)
            )
        case ExcelDataDomain.LIST_REPORT_FILINGS:
            return ListReportFilingsQuery(
                ListReportFilingsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.LIST_REPORT_ATTACHMENTS:
            return ListReportAttachmentsQuery(
                ListReportAttachmentsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.LIST_REPORT_SECTIONS:
            return ListReportSectionsQuery(
                ListReportSectionsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_REPORT_SECTIONS:
            return GetReportSectionsQuery(
                GetReportSectionsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_COMPANY_PROFILE:
            return GetCompanyProfileQuery(
                GetCompanyProfileArguments.model_validate(arguments)
            )


def _validated_financial_query(
    domain: FinancialDomain,
    arguments: JsonObject,
) -> ValidatedExcelQuery:
    match domain:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
        case ExcelDataDomain.GET_FINANCIAL_STATEMENTS:
            return GetFinancialStatementsQuery(
                GetFinancialStatementsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_MAJOR_ACCOUNTS:
            return GetMajorAccountsQuery(
                GetMajorAccountsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_FINANCIAL_INDICATORS:
            return GetFinancialIndicatorsQuery(
                GetFinancialIndicatorsArguments.model_validate(arguments)
            )


def _validated_disclosure_query(
    domain: DisclosureDomain,
    arguments: JsonObject,
) -> ValidatedExcelQuery:
    match domain:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
        case ExcelDataDomain.GET_REPORT_TOPICS:
            return GetReportTopicsQuery(
                GetReportTopicsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_OWNERSHIP_REPORTS:
            return GetOwnershipReportsQuery(
                GetOwnershipReportsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_MATERIAL_EVENTS:
            return GetMaterialEventsQuery(
                GetMaterialEventsArguments.model_validate(arguments)
            )
        case ExcelDataDomain.GET_REGISTRATION_STATEMENTS:
            return GetRegistrationStatementsQuery(
                GetRegistrationStatementsArguments.model_validate(arguments)
            )
