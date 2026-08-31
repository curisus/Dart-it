import pytest

from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.query_limits import EXCEL_POLICY
from dart_crawler.result import ErrorCode, JsonObject, JsonValue
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _corp_codes(count: int) -> list[str]:
    return [f"{index:08d}" for index in range(count)]


def _json_codes(codes: list[str]) -> list[JsonValue]:
    values: list[JsonValue] = []
    values.extend(codes)
    return values


def test_major_accounts_dispatches_one_unsplit_hundred_company_call() -> None:
    codes = _corp_codes(100)
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    arguments: JsonObject = {
        "corp_codes": _json_codes(codes),
        "bsns_year": 2025,
        "reprt_code": "11011",
    }
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments=arguments,
    )

    result = execute_normalized_excel_query(request, factory)

    assert result.ok
    assert result.data is not None
    assert result.data.validated_arguments["corp_codes"] == codes
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1
    assert factory.services[0].calls[0].arguments["corp_codes"] == codes


def test_financial_indicators_dispatches_one_unsplit_hundred_company_call() -> None:
    codes = _corp_codes(100)
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    arguments: JsonObject = {
        "corp_codes": _json_codes(codes),
        "bsns_year": 2025,
        "reprt_code": "11011",
        "idx_cl_code": "M210000",
    }
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_FINANCIAL_INDICATORS,
        arguments=arguments,
    )

    result = execute_normalized_excel_query(request, factory)

    assert result.ok
    assert result.data is not None
    assert result.data.validated_arguments["corp_codes"] == codes
    assert factory.policies == [EXCEL_POLICY]
    assert len(factory.services) == 1
    assert len(factory.services[0].calls) == 1
    assert factory.services[0].calls[0].arguments["corp_codes"] == codes


def test_major_accounts_rejects_101_before_service_creation() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    arguments: JsonObject = {
        "corp_codes": _json_codes(_corp_codes(101)),
        "bsns_year": 2025,
        "reprt_code": "11011",
    }
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments=arguments,
    )

    result = execute_normalized_excel_query(request, factory)

    assert not result.ok
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.retryable is False
    assert result.error.details == {"reason": "invalid_request"}
    assert factory.policies == []
    assert factory.services == []


def test_financial_indicators_rejects_101_before_service_creation() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())
    arguments: JsonObject = {
        "corp_codes": _json_codes(_corp_codes(101)),
        "bsns_year": 2025,
        "reprt_code": "11011",
        "idx_cl_code": "M210000",
    }
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_FINANCIAL_INDICATORS,
        arguments=arguments,
    )

    result = execute_normalized_excel_query(request, factory)

    assert not result.ok
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.retryable is False
    assert result.error.details == {"reason": "invalid_request"}
    assert factory.policies == []
    assert factory.services == []


@pytest.mark.parametrize(
    "excel_request",
    [
        ExcelLoadRequest(
            domain=ExcelDataDomain.SEARCH_COMPANIES,
            arguments={"company_query": "회사", "unexpected": "value"},
        ),
        ExcelLoadRequest(
            domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
            arguments={
                "corp_codes": _json_codes(_corp_codes(101)),
                "bsns_year": 2025,
                "reprt_code": "11011",
            },
        ),
        ExcelLoadRequest(
            domain=ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
            arguments={
                "corp_code": "00123456",
                "bsns_year": True,
                "reprt_code": "11011",
            },
        ),
    ],
    ids=["extra-field", "101-companies", "bool-as-int"],
)
def test_invalid_requests_use_central_invalid_request_result(
    excel_request: ExcelLoadRequest,
) -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    result = execute_normalized_excel_query(excel_request, factory)

    assert result.model_dump(mode="json") == {
        "ok": False,
        "data": None,
        "error": {
            "code": "INVALID_INPUT",
            "message": "Excel 페이지 요청을 완료할 수 없습니다.",
            "retryable": False,
            "details": {"reason": "invalid_request"},
        },
        "warnings": [],
        "next_action": None,
    }
    assert factory.policies == []
    assert factory.services == []
