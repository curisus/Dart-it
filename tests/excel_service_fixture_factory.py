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
from tests.excel_service_responses import ExcelServiceResponses


def empty_excel_service_responses() -> ExcelServiceResponses:
    return ExcelServiceResponses(
        search_companies=Result.success(()),
        list_report_filings=Result.success(()),
        list_report_attachments=Result.success(()),
        list_report_sections=Result.success(
            ReportSectionList(
                rcept_no="20260101000001",
                attachment_id="opendart:20260101000001:test.xml",
                report_title=None,
                source_type="xml",
                source_sha256="a" * 64,
                parser_version="0.1.0",
                coverage_complete=True,
                section_count=0,
                total_cell_count=0,
                total_text_char_count=0,
                sections=(),
            )
        ),
        get_report_sections=Result.success(
            ReportSectionData(
                rcept_no="20260101000001",
                attachment_id="opendart:20260101000001:test.xml",
                source_sha256="a" * 64,
                parser_version="0.1.0",
                returned_cell_count=0,
                returned_text_char_count=0,
                sections=(),
            )
        ),
        get_financial_statements=Result.success(
            FinancialStatementData(
                corp_code="00123456",
                bsns_year=2025,
                reprt_code="11011",
                fs_div="CFS",
                returned_row_count=0,
                accounts=(),
            )
        ),
        get_major_accounts=Result.success(
            MajorAccountData(
                corp_codes=("00123456",),
                bsns_year=2025,
                reprt_code="11011",
                returned_row_count=0,
                accounts=(),
            )
        ),
        get_financial_indicators=Result.success(
            FinancialIndicatorData(
                corp_codes=("00123456",),
                bsns_year=2025,
                reprt_code="11011",
                idx_cl_code="M210000",
                returned_row_count=0,
                empty_indicator_count=0,
                indicators=(),
            )
        ),
        get_report_topics=Result.success(
            ReportTopicData(
                corp_code="00123456",
                bsns_year=2025,
                reprt_code="11011",
                returned_row_count=0,
                topics=(),
            )
        ),
        get_company_profile=Result.success(_empty_company_profile()),
        get_ownership_reports=Result.success(
            OwnershipReportData(
                corp_code="00123456",
                report_type="major_holding",
                label="label",
                bgn_de="",
                end_de="",
                total_row_count=0,
                returned_row_count=0,
                rows=(),
            )
        ),
        get_material_events=Result.success(
            MaterialEventData(
                corp_code="00123456",
                bgn_de="20250101",
                end_de="20251231",
                returned_row_count=0,
                events=(),
            )
        ),
        get_registration_statements=Result.success(
            RegistrationStatementData(
                corp_code="00123456",
                stmt_type="equity_securities",
                label="label",
                bgn_de="20250101",
                end_de="20251231",
                returned_group_count=0,
                returned_row_count=0,
                groups=(),
            )
        ),
    )


def _empty_company_profile() -> CompanyProfileData:
    return CompanyProfileData(
        corp_code="00123456",
        corp_name="",
        corp_name_eng="",
        stock_name="",
        stock_code="",
        ceo_nm="",
        corp_cls="",
        jurir_no="",
        bizr_no="",
        adres="",
        hm_url="",
        ir_url="",
        phn_no="",
        fax_no="",
        induty_code="",
        est_dt="",
        acc_mt="",
    )
