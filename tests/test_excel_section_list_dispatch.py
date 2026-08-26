from dataclasses import replace

from dart_crawler.document_model import SectionKind
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.section_models import ReportSectionList, SectionSummary
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_RCEPT_NO = "20260101000001"
_ATTACHMENT_ID = f"opendart:{_RCEPT_NO}:report.xml"


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.LIST_REPORT_SECTIONS,
        arguments={"rcept_no": _RCEPT_NO, "attachment_id": _ATTACHMENT_ID},
        page_size=100,
    )


def _section(identifier: str, title: str) -> SectionSummary:
    return SectionSummary(
        section_id=identifier,
        title=title,
        kind=SectionKind.OTHER,
        block_count=1,
        table_count=0,
        cell_count=0,
        text_char_count=len(title),
        has_image=False,
    )


def _source(sections: tuple[SectionSummary, ...]) -> ReportSectionList:
    return ReportSectionList(
        rcept_no=_RCEPT_NO,
        attachment_id=_ATTACHMENT_ID,
        report_title="보고서",
        source_type="xml",
        source_sha256="b" * 64,
        parser_version="2.0.0",
        coverage_complete=True,
        section_count=len(sections),
        total_cell_count=0,
        total_text_char_count=sum(item.text_char_count for item in sections),
        sections=sections,
    )


def test_list_report_sections_preserves_section_order_and_provenance() -> None:
    source = Result.success(
        _source((_section("s001-other", "첫째"), _section("s002-other", "둘째")))
    )
    responses = replace(
        empty_excel_service_responses(),
        list_report_sections=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "rcept_no",
        "attachment_id",
        "report_title",
        "source_type",
        "source_sha256",
        "parser_version",
        "coverage_complete",
        "section_id",
        "title",
        "kind",
        "block_count",
        "table_count",
        "cell_count",
        "text_char_count",
        "has_image",
    )
    assert tuple(row["title"] for row in result.data.rows) == ("첫째", "둘째")
    assert result.data.provenance.source_sha256 == "b" * 64
    assert result.data.provenance.parser_version == "2.0.0"
    assert len(factory.services[0].calls) == 1


def test_list_report_sections_empty_retains_baseline_columns() -> None:
    source = Result.success(_source(()))
    responses = replace(
        empty_excel_service_responses(),
        list_report_sections=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns[-1] == "has_image"
    assert len(factory.services[0].calls) == 1


def test_list_report_sections_preserves_existing_failure() -> None:
    error = error_info(
        ErrorCode.PARSE_FAILED,
        "parse failed",
        retryable=False,
        details={"reason": "public"},
    )
    source = Result[ReportSectionList].failure(error, next_action="choose xml")
    responses = replace(
        empty_excel_service_responses(),
        list_report_sections=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "choose xml"
    assert len(factory.services[0].calls) == 1
