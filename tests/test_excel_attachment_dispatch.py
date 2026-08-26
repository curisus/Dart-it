from dataclasses import replace

from dart_crawler.domain import Attachment
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
        arguments={"rcept_no": "20260101000001"},
        page_size=100,
    )


def _attachment(name: str) -> Attachment:
    return Attachment(
        attachment_id=f"opendart:20260101000001:{name}",
        rcept_no="20260101000001",
        source_rcept_no="20260101000001",
        title=name,
        source="opendart",
        standalone=True,
        filename=name,
    )


def test_list_report_attachments_preserves_source_order() -> None:
    source: Result[tuple[Attachment, ...]] = Result.success(
        (_attachment("first.xml"), _attachment("second.xml"))
    )
    responses = replace(
        empty_excel_service_responses(),
        list_report_attachments=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "rcept_no",
        "attachment_id",
        "source_rcept_no",
        "title",
        "source",
        "standalone",
        "filename",
        "dcm_no",
    )
    assert tuple(row["title"] for row in result.data.rows) == (
        "first.xml",
        "second.xml",
    )
    assert len(factory.services[0].calls) == 1


def test_list_report_attachments_empty_retains_baseline_columns() -> None:
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns[0] == "rcept_no"
    assert "attachment_id" in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_list_report_attachments_preserves_existing_failure() -> None:
    error = error_info(
        ErrorCode.UPSTREAM_LAYOUT_CHANGED,
        "layout changed",
        retryable=False,
        details={"public": "detail"},
    )
    source = Result[tuple[Attachment, ...]].failure(
        error,
        next_action="select another filing",
    )
    responses = replace(
        empty_excel_service_responses(),
        list_report_attachments=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "select another filing"
    assert len(factory.services[0].calls) == 1
