from typing import assert_never

from dart_crawler.excel_argument_validation import validate_excel_query
from dart_crawler.excel_company_normalization import (
    normalize_company_profile,
    normalize_list_report_attachments,
    normalize_list_report_filings,
)
from dart_crawler.excel_dataset_builder import preserve_excel_failure
from dart_crawler.excel_disclosure_normalization import (
    normalize_material_events,
    normalize_ownership_reports,
    normalize_registration_statements,
    normalize_report_topics,
)
from dart_crawler.excel_financial_normalization import (
    normalize_financial_indicators,
    normalize_financial_statements,
    normalize_major_accounts,
)
from dart_crawler.excel_page_models import ExcelLoadRequest
from dart_crawler.excel_query_service import ExcelQueryService, ExcelQueryServiceFactory
from dart_crawler.excel_search_normalization import normalize_search_companies
from dart_crawler.excel_section_normalization import (
    normalize_get_report_sections,
    normalize_list_report_sections,
)
from dart_crawler.excel_validated_queries import (
    DisclosureValidatedExcelQuery,
    FinancialValidatedExcelQuery,
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
    ReportValidatedExcelQuery,
    SearchCompaniesQuery,
    ValidatedExcelQuery,
)
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import Result


def execute_normalized_excel_query(
    request: ExcelLoadRequest,
    factory: ExcelQueryServiceFactory,
) -> Result[NormalizedExcelDataset]:
    validated = validate_excel_query(request.domain, request.arguments)
    if not validated.ok or validated.data is None:
        return preserve_excel_failure(validated)
    service = factory.create(EXCEL_POLICY)
    return _dispatch_validated_query(validated.data, service)


def _dispatch_validated_query(
    query: ValidatedExcelQuery,
    service: ExcelQueryService,
) -> Result[NormalizedExcelDataset]:
    match query:
        case (
            SearchCompaniesQuery()
            | ListReportFilingsQuery()
            | ListReportAttachmentsQuery()
            | ListReportSectionsQuery()
            | GetReportSectionsQuery()
            | GetCompanyProfileQuery()
        ) as report_query:
            return _dispatch_report_query(report_query, service)
        case (
            GetFinancialStatementsQuery()
            | GetMajorAccountsQuery()
            | GetFinancialIndicatorsQuery()
        ) as financial_query:
            return _dispatch_financial_query(financial_query, service)
        case (
            GetReportTopicsQuery()
            | GetOwnershipReportsQuery()
            | GetMaterialEventsQuery()
            | GetRegistrationStatementsQuery()
        ) as disclosure_query:
            return _dispatch_disclosure_query(disclosure_query, service)
        case unreachable:
            assert_never(unreachable)


def _dispatch_report_query(
    query: ReportValidatedExcelQuery,
    service: ExcelQueryService,
) -> Result[NormalizedExcelDataset]:
    match query:
        case SearchCompaniesQuery(arguments=arguments):
            return normalize_search_companies(
                arguments,
                service.search_companies(
                    arguments.company_query,
                    arguments.report_kind,
                ),
            )
        case ListReportFilingsQuery(arguments=arguments):
            return normalize_list_report_filings(
                arguments,
                service.list_report_filings(
                    arguments.corp_code,
                    arguments.report_kind,
                ),
            )
        case ListReportAttachmentsQuery(arguments=arguments):
            return normalize_list_report_attachments(
                arguments,
                service.list_report_attachments(arguments.rcept_no),
            )
        case ListReportSectionsQuery(arguments=arguments):
            return normalize_list_report_sections(
                arguments,
                service.list_report_sections(
                    arguments.rcept_no,
                    arguments.attachment_id,
                ),
            )
        case GetReportSectionsQuery(arguments=arguments):
            return normalize_get_report_sections(
                arguments,
                service.get_report_sections(
                    arguments.rcept_no,
                    arguments.attachment_id,
                    arguments.section_ids,
                    arguments.section_kinds,
                ),
            )
        case GetCompanyProfileQuery(arguments=arguments):
            return normalize_company_profile(
                arguments,
                service.get_company_profile(arguments.corp_code),
            )
        case unreachable:
            assert_never(unreachable)


def _dispatch_financial_query(
    query: FinancialValidatedExcelQuery,
    service: ExcelQueryService,
) -> Result[NormalizedExcelDataset]:
    match query:
        case GetFinancialStatementsQuery(arguments=arguments):
            return normalize_financial_statements(
                arguments,
                service.get_financial_statements(
                    arguments.corp_code,
                    arguments.bsns_year,
                    arguments.reprt_code,
                    arguments.fs_div,
                ),
            )
        case GetMajorAccountsQuery(arguments=arguments):
            return normalize_major_accounts(
                arguments,
                service.get_major_accounts(
                    arguments.corp_codes,
                    arguments.bsns_year,
                    arguments.reprt_code,
                ),
            )
        case GetFinancialIndicatorsQuery(arguments=arguments):
            return normalize_financial_indicators(
                arguments,
                service.get_financial_indicators(
                    arguments.corp_codes,
                    arguments.bsns_year,
                    arguments.reprt_code,
                    arguments.idx_cl_code,
                ),
            )
        case unreachable:
            assert_never(unreachable)


def _dispatch_disclosure_query(
    query: DisclosureValidatedExcelQuery,
    service: ExcelQueryService,
) -> Result[NormalizedExcelDataset]:
    match query:
        case GetReportTopicsQuery(arguments=arguments):
            return normalize_report_topics(
                arguments,
                service.get_report_topics(
                    arguments.corp_code,
                    arguments.bsns_year,
                    arguments.reprt_code,
                    arguments.topics,
                ),
            )
        case GetOwnershipReportsQuery(arguments=arguments):
            return normalize_ownership_reports(
                arguments,
                service.get_ownership_reports(
                    arguments.corp_code,
                    arguments.report_type,
                    arguments.bgn_de,
                    arguments.end_de,
                ),
            )
        case GetMaterialEventsQuery(arguments=arguments):
            return normalize_material_events(
                arguments,
                service.get_material_events(
                    arguments.corp_code,
                    arguments.event_types,
                    arguments.bgn_de,
                    arguments.end_de,
                ),
            )
        case GetRegistrationStatementsQuery(arguments=arguments):
            return normalize_registration_statements(
                arguments,
                service.get_registration_statements(
                    arguments.corp_code,
                    arguments.stmt_type,
                    arguments.bgn_de,
                    arguments.end_de,
                ),
            )
        case unreachable:
            assert_never(unreachable)
