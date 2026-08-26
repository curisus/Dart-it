from dataclasses import replace

from dart_crawler.domains.company_profile import CompanyProfileData
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_COMPANY_PROFILE,
        arguments={"corp_code": "00123456"},
        page_size=100,
    )


def _profile(name: str) -> CompanyProfileData:
    return CompanyProfileData(
        corp_code="00123456",
        corp_name=name,
        corp_name_eng="Company",
        stock_name="회사",
        stock_code="123456",
        ceo_nm="대표",
        corp_cls="Y",
        jurir_no="1101110000000",
        bizr_no="1234567890",
        adres="서울",
        hm_url="https://example.invalid",
        ir_url="",
        phn_no="02-0000-0000",
        fax_no="",
        induty_code="00000",
        est_dt="20000101",
        acc_mt="12",
    )


def test_company_profile_success_is_exactly_one_declared_row() -> None:
    responses = replace(
        empty_excel_service_responses(),
        get_company_profile=Result.success(_profile("회사")),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "corp_code",
        "corp_name",
        "corp_name_eng",
        "stock_name",
        "stock_code",
        "ceo_nm",
        "corp_cls",
        "jurir_no",
        "bizr_no",
        "adres",
        "hm_url",
        "ir_url",
        "phn_no",
        "fax_no",
        "induty_code",
        "est_dt",
        "acc_mt",
    )
    assert len(result.data.rows) == 1
    assert result.data.rows[0]["corp_name"] == "회사"
    assert len(factory.services[0].calls) == 1


def test_company_profile_empty_fields_still_form_one_row() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert len(result.data.rows) == 1
    assert result.data.rows[0]["corp_name"] == ""
    assert len(factory.services[0].calls) == 1


def test_company_profile_preserves_existing_failure() -> None:
    error = error_info(
        ErrorCode.NOT_FOUND,
        "company not found",
        retryable=False,
    )
    source = Result[CompanyProfileData].failure(error, next_action="search company")
    responses = replace(
        empty_excel_service_responses(),
        get_company_profile=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "search company"
    assert len(factory.services[0].calls) == 1
