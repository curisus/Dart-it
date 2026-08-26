from dataclasses import replace

from dart_crawler.domains.registration_statements import (
    RegistrationStatementData,
    RegistrationStatementGroup,
)
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
        arguments={
            "corp_code": "00123456",
            "stmt_type": "equity_securities",
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
        page_size=100,
    )


def _data(
    groups: tuple[RegistrationStatementGroup, ...],
) -> RegistrationStatementData:
    return RegistrationStatementData(
        corp_code="00123456",
        stmt_type="equity_securities",
        label="지분증권",
        bgn_de="20250101",
        end_de="20251231",
        returned_group_count=len(groups),
        returned_row_count=sum(group.row_count for group in groups),
        groups=groups,
    )


def test_registration_statements_preserve_group_then_row_order() -> None:
    groups = (
        RegistrationStatementGroup(
            title="첫 그룹",
            row_count=2,
            rows=({"name": "A", "first": 1}, {"name": "B"}),
        ),
        RegistrationStatementGroup(
            title="둘째 그룹",
            row_count=1,
            rows=({"name": "C", "later": 2},),
        ),
    )
    responses = replace(
        empty_excel_service_responses(),
        get_registration_statements=Result.success(_data(groups)),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "corp_code",
        "stmt_type",
        "label",
        "bgn_de",
        "end_de",
        "group_index",
        "group_title",
        "name",
        "first",
        "later",
    )
    assert tuple(row["name"] for row in result.data.rows) == ("A", "B", "C")
    assert tuple(row["group_index"] for row in result.data.rows) == (1, 1, 2)
    assert result.data.provenance.reported_groups == 2
    assert result.data.provenance.reported_rows == 3
    assert len(factory.services[0].calls) == 1


def test_registration_statements_empty_retains_group_baseline() -> None:
    responses = replace(
        empty_excel_service_responses(),
        get_registration_statements=Result.success(_data(())),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns == (
        "corp_code",
        "stmt_type",
        "label",
        "bgn_de",
        "end_de",
        "group_index",
        "group_title",
    )
    assert len(factory.services[0].calls) == 1


def test_registration_statements_preserve_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_LAYOUT_CHANGED,
        "registration layout changed",
        retryable=False,
    )
    source = Result[RegistrationStatementData].failure(
        error,
        next_action="retry later",
    )
    responses = replace(
        empty_excel_service_responses(),
        get_registration_statements=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "retry later"
    assert len(factory.services[0].calls) == 1
