from dataclasses import replace

from dart_crawler.domains.material_events import MaterialEventData, MaterialEventRows
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_EVENT_TYPES = ("merger", "bankruptcy")


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MATERIAL_EVENTS,
        arguments={
            "corp_code": "00123456",
            "event_types": list(_EVENT_TYPES),
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
        page_size=100,
    )


def _data(groups: tuple[MaterialEventRows, ...]) -> MaterialEventData:
    return MaterialEventData(
        corp_code="00123456",
        bgn_de="20250101",
        end_de="20251231",
        returned_row_count=sum(group.row_count for group in groups),
        events=groups,
    )


def test_material_events_use_requested_event_order_then_source_rows() -> None:
    bankruptcy = MaterialEventRows(
        event_type="bankruptcy",
        label="파산",
        row_count=1,
        rows=({"receipt": "B"},),
    )
    merger = MaterialEventRows(
        event_type="merger",
        label="합병",
        row_count=2,
        rows=({"receipt": "M1", "first": 1}, {"receipt": "M2", "second": 2}),
    )
    responses = replace(
        empty_excel_service_responses(),
        get_material_events=Result.success(_data((bankruptcy, merger))),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "corp_code",
        "event_type",
        "label",
        "bgn_de",
        "end_de",
        "receipt",
        "first",
        "second",
    )
    assert tuple(row["receipt"] for row in result.data.rows) == ("M1", "M2", "B")
    assert tuple(row["event_type"] for row in result.data.rows) == (
        "merger",
        "merger",
        "bankruptcy",
    )
    assert len(factory.services[0].calls) == 1


def test_material_events_all_empty_retains_group_baseline() -> None:
    groups = tuple(
        MaterialEventRows(event_type=kind, label=kind, row_count=0, rows=())
        for kind in reversed(_EVENT_TYPES)
    )
    responses = replace(
        empty_excel_service_responses(),
        get_material_events=Result.success(_data(groups)),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns == (
        "corp_code",
        "event_type",
        "label",
        "bgn_de",
        "end_de",
    )
    assert len(factory.services[0].calls) == 1


def test_material_events_preserve_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_AUTH,
        "events auth failed",
        retryable=False,
    )
    source = Result[MaterialEventData].failure(error, next_action="check key")
    responses = replace(
        empty_excel_service_responses(),
        get_material_events=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "check key"
    assert len(factory.services[0].calls) == 1
