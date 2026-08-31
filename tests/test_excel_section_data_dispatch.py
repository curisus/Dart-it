from dataclasses import replace

from dart_crawler.document_model import BlockKind, SectionKind
from dart_crawler.excel_normalized_dispatch import execute_normalized_excel_query
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelLoadRequest
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.section_models import (
    ReportSectionData,
    SectionBlock,
    SectionData,
    TableData,
)
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses

_RCEPT_NO = "20260101000001"
_ATTACHMENT_ID = f"opendart:{_RCEPT_NO}:report.xml"


def _request() -> ExcelLoadRequest:
    return ExcelLoadRequest(
        domain=ExcelDataDomain.GET_REPORT_SECTIONS,
        arguments={
            "rcept_no": _RCEPT_NO,
            "attachment_id": _ATTACHMENT_ID,
            "section_ids": ["s001-other"],
        },
        page_size=100,
    )


def _source(sections: tuple[SectionData, ...]) -> ReportSectionData:
    return ReportSectionData(
        rcept_no=_RCEPT_NO,
        attachment_id=_ATTACHMENT_ID,
        source_sha256="c" * 64,
        parser_version="2.0.0",
        returned_cell_count=4,
        returned_text_char_count=8,
        sections=sections,
    )


def test_get_report_sections_flattens_blocks_and_table_rows_in_source_order() -> None:
    section = SectionData(
        section_id="s001-other",
        title="본문",
        kind=SectionKind.OTHER,
        blocks=(
            SectionBlock(kind=BlockKind.HEADING, text="제목"),
            SectionBlock(
                kind=BlockKind.TABLE,
                table=TableData(
                    rows=(("A", "B"), ("C", "D")),
                    merged_ranges=((1, 1, 1, 2),),
                ),
            ),
            SectionBlock(
                kind=BlockKind.IMAGE,
                text="대체 문구",
                image_source="image-1.png",
            ),
        ),
    )
    responses = replace(
        empty_excel_service_responses(),
        get_report_sections=Result.success(_source((section,))),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.columns == (
        "rcept_no",
        "attachment_id",
        "section_id",
        "section_title",
        "section_kind",
        "block_index",
        "block_kind",
        "table_row_index",
        "text",
        "image_source",
        "merged_ranges",
        "column_1",
        "column_2",
    )
    assert tuple(row["block_kind"] for row in result.data.rows) == (
        "heading",
        "table",
        "table",
        "image",
    )
    assert tuple(row["table_row_index"] for row in result.data.rows) == (
        None,
        1,
        2,
        None,
    )
    assert result.data.rows[1]["merged_ranges"] == "[[1,1,1,2]]"
    assert result.data.rows[2]["column_2"] == "D"
    assert result.data.rows[3]["image_source"] == "image-1.png"
    assert result.data.provenance.source_blocks == 3
    assert len(factory.services[0].calls) == 1


def test_get_report_sections_empty_retains_fixed_block_columns() -> None:
    responses = replace(
        empty_excel_service_responses(),
        get_report_sections=Result.success(_source(())),
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.columns[-1] == "merged_ranges"
    assert "column_1" not in result.data.columns
    assert len(factory.services[0].calls) == 1


def test_get_report_sections_preserves_existing_failure_without_partial_rows() -> None:
    error = error_info(
        ErrorCode.VALIDATION_FAILED,
        "source validation failed",
        retryable=False,
        details={"reason": "coverage"},
    )
    source = Result[ReportSectionData].failure(
        error,
        next_action="select fewer sections",
    )
    responses = replace(
        empty_excel_service_responses(),
        get_report_sections=source,
    )
    factory = RecordingExcelServiceFactory(responses)

    result = execute_normalized_excel_query(_request(), factory)

    assert not result.ok
    assert result.data is None
    assert result.error == error
    assert result.next_action == "select fewer sections"
    assert len(factory.services[0].calls) == 1
