from dataclasses import replace

from dart_crawler.domains.report_topics import ReportTopicData, ReportTopicRows
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_TOPICS = ("dividend", "audit_opinion")


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_REPORT_TOPICS,
        arguments={
            "corp_code": "00123456",
            "bsns_year": 2025,
            "reprt_code": "11011",
            "topics": list(_TOPICS),
        },
        page_size=100,
    )


def _data(groups: tuple[ReportTopicRows, ...]) -> ReportTopicData:
    return ReportTopicData(
        corp_code="00123456",
        bsns_year=2025,
        reprt_code="11011",
        returned_row_count=sum(group.row_count for group in groups),
        topics=groups,
    )


def test_report_topics_use_requested_group_order_and_first_seen_keys() -> None:
    audit = ReportTopicRows(
        topic="audit_opinion",
        label="감사의견",
        row_count=1,
        rows=({"z": "audit", "later": 2},),
    )
    dividend = ReportTopicRows(
        topic="dividend",
        label="배당",
        row_count=1,
        rows=(
            {
                "corp_code": "00123456",
                "z": "dividend",
                "nested": {"b": 2, "a": [2, 1]},
            },
        ),
    )
    responses = replace(
        empty_excel_service_responses(),
        get_report_topics=Result.success(_data((audit, dividend))),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "corp_code",
        "bsns_year",
        "reprt_code",
        "topic",
        "label",
        "z",
        "nested",
        "later",
    )
    assert tuple(row["topic"] for row in result.data.rows) == _TOPICS
    assert result.data.rows[0]["nested"] == '{"a":[2,1],"b":2}'
    assert len(factory.services[0].calls) == 1


def test_report_topics_all_empty_retains_group_baseline() -> None:
    groups = tuple(
        ReportTopicRows(topic=topic, label=topic, row_count=0, rows=())
        for topic in reversed(_TOPICS)
    )
    responses = replace(
        empty_excel_service_responses(),
        get_report_topics=Result.success(_data(groups)),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns == (
        "corp_code",
        "bsns_year",
        "reprt_code",
        "topic",
        "label",
    )
    assert len(factory.services[0].calls) == 1


def test_report_topics_preserve_existing_group_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "topic source failed",
        retryable=True,
    )
    source = Result[ReportTopicData].failure(error, next_action="retry")
    responses = replace(
        empty_excel_service_responses(),
        get_report_topics=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "retry"
    assert len(factory.services[0].calls) == 1
