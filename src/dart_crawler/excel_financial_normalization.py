from dart_crawler.api_models import (
    FinancialAccount,
    FinancialIndexRow,
    MajorAccountRow,
)
from dart_crawler.domains.financials import (
    FinancialIndicatorData,
    FinancialStatementData,
    MajorAccountData,
)
from dart_crawler.excel_dataset_builder import preserve_excel_failure
from dart_crawler.excel_financial_arguments import (
    GetFinancialIndicatorsArguments,
    GetFinancialStatementsArguments,
    GetMajorAccountsArguments,
)
from dart_crawler.excel_model_row_normalization import normalize_model_rows
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_row_normalization import ExcelSourceValue, SourcePairs
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result


def normalize_financial_statements(
    arguments: GetFinancialStatementsArguments,
    result: Result[FinancialStatementData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    context = (
        ("corp_code", arguments.corp_code),
        ("bsns_year", arguments.bsns_year),
        ("reprt_code", arguments.reprt_code),
        ("fs_div", arguments.fs_div),
    )
    return normalize_model_rows(
        domain=ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
        arguments=arguments,
        context_columns=tuple(name for name, _value in context),
        context=context,
        source_model=FinancialAccount,
        models=source.accounts,
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
            source_rows=len(source.accounts),
            normalized_rows=len(source.accounts),
            reported_rows=source.returned_row_count,
        ),
    )


def normalize_major_accounts(
    arguments: GetMajorAccountsArguments,
    result: Result[MajorAccountData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    context: SourcePairs = (
        ("corp_codes", _company_codes(arguments.corp_codes)),
        ("bsns_year", arguments.bsns_year),
        ("reprt_code", arguments.reprt_code),
    )
    return normalize_model_rows(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments=arguments,
        context_columns=tuple(name for name, _value in context),
        context=context,
        source_model=MajorAccountRow,
        models=source.accounts,
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
            source_rows=len(source.accounts),
            normalized_rows=len(source.accounts),
            reported_rows=source.returned_row_count,
        ),
    )


def normalize_financial_indicators(
    arguments: GetFinancialIndicatorsArguments,
    result: Result[FinancialIndicatorData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    context: SourcePairs = (
        ("corp_codes", _company_codes(arguments.corp_codes)),
        ("bsns_year", arguments.bsns_year),
        ("reprt_code", arguments.reprt_code),
        ("idx_cl_code", arguments.idx_cl_code),
    )
    return normalize_model_rows(
        domain=ExcelDataDomain.GET_FINANCIAL_INDICATORS,
        arguments=arguments,
        context_columns=tuple(name for name, _value in context),
        context=context,
        source_model=FinancialIndexRow,
        models=source.indicators,
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.GET_FINANCIAL_INDICATORS,
            source_rows=len(source.indicators),
            normalized_rows=len(source.indicators),
            reported_rows=source.returned_row_count,
        ),
    )


def _company_codes(values: tuple[str, ...]) -> list[ExcelSourceValue]:
    codes: list[ExcelSourceValue] = []
    codes.extend(values)
    return codes
