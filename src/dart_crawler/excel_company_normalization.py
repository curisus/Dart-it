from dart_crawler.domain import Attachment, Filing
from dart_crawler.domains.company_profile import CompanyProfileData
from dart_crawler.excel_company_arguments import (
    GetCompanyProfileArguments,
    ListReportAttachmentsArguments,
    ListReportFilingsArguments,
)
from dart_crawler.excel_dataset_builder import preserve_excel_failure
from dart_crawler.excel_model_row_normalization import normalize_model_rows
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result


def normalize_list_report_filings(
    arguments: ListReportFilingsArguments,
    result: Result[tuple[Filing, ...]],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    return normalize_model_rows(
        domain=ExcelDataDomain.LIST_REPORT_FILINGS,
        arguments=arguments,
        context_columns=("corp_code", "report_kind"),
        context=(
            ("corp_code", arguments.corp_code),
            ("report_kind", arguments.report_kind),
        ),
        source_model=Filing,
        models=result.data,
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.LIST_REPORT_FILINGS,
            source_rows=len(result.data),
            normalized_rows=len(result.data),
        ),
    )


def normalize_list_report_attachments(
    arguments: ListReportAttachmentsArguments,
    result: Result[tuple[Attachment, ...]],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    return normalize_model_rows(
        domain=ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
        arguments=arguments,
        context_columns=("rcept_no",),
        context=(("rcept_no", arguments.rcept_no),),
        source_model=Attachment,
        models=result.data,
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
            source_rows=len(result.data),
            normalized_rows=len(result.data),
        ),
    )


def normalize_company_profile(
    arguments: GetCompanyProfileArguments,
    result: Result[CompanyProfileData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    return normalize_model_rows(
        domain=ExcelDataDomain.GET_COMPANY_PROFILE,
        arguments=arguments,
        context_columns=("corp_code",),
        context=(("corp_code", arguments.corp_code),),
        source_model=CompanyProfileData,
        models=(result.data,),
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.GET_COMPANY_PROFILE,
            source_rows=1,
            normalized_rows=1,
        ),
    )
