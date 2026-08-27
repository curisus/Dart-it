import pytest
from pydantic import SecretStr

from dart_crawler.crawler_service import PARSER_VERSION, CrawlerService, LoadedDocument
from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
    SourceCoverage,
)
from dart_crawler.result import ErrorCode, Result, WarningCode
from tests.report_section_test_support import (
    ATTACHMENT_ID,
    RCEPT_NO,
    NetworkRejectingHttpClient,
    report_xml,
    service_reading,
)


def test_list_report_sections_summarizes_every_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_reading(monkeypatch, report_xml())

    result = service.list_report_sections(RCEPT_NO, ATTACHMENT_ID)

    assert result.ok is True
    assert result.data is not None
    listing = result.data
    assert listing.rcept_no == RCEPT_NO
    assert listing.attachment_id == ATTACHMENT_ID
    assert listing.report_title == "독립된 감사인의 감사보고서"
    assert listing.source_type == "xml"
    assert len(listing.source_sha256) == 64
    assert listing.parser_version == PARSER_VERSION
    assert listing.coverage_complete is True
    assert listing.section_count == 5
    assert [section.section_id for section in listing.sections] == [
        "s001-opinion",
        "s002-balance_sheet",
        "s003-income",
        "s004-equity",
        "s005-cash_flow",
    ]
    assert listing.total_cell_count == sum(
        section.cell_count for section in listing.sections
    )
    assert listing.total_cell_count == 16
    assert listing.total_text_char_count == sum(
        section.text_char_count for section in listing.sections
    )
    assert listing.total_text_char_count == 46
    assert result.warnings == ()


def test_get_report_sections_returns_only_the_selected_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_reading(monkeypatch, report_xml())

    result = service.get_report_sections(
        RCEPT_NO,
        ATTACHMENT_ID,
        section_ids=("s001-opinion",),
        section_kinds=("cash_flow",),
    )

    assert result.ok is True
    assert result.data is not None
    selected = result.data
    assert [section.section_id for section in selected.sections] == [
        "s001-opinion",
        "s005-cash_flow",
    ]
    assert selected.parser_version == PARSER_VERSION
    assert selected.returned_cell_count == 4
    assert selected.returned_text_char_count == 31
    cash_flow_table = selected.sections[1].blocks[1].table
    assert cash_flow_table is not None
    assert cash_flow_table.rows == (
        ("계정", "당기"),
        ("현금및현금성자산", "200"),
    )
    assert result.warnings == ()


def test_get_report_sections_rejects_a_selection_that_matches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_reading(monkeypatch, report_xml())

    result = service.get_report_sections(
        RCEPT_NO,
        ATTACHMENT_ID,
        section_ids=("s099-note",),
    )

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_missing_core_statement_warns_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_reading(monkeypatch, report_xml(with_cash_flow=False))

    listing = service.list_report_sections(RCEPT_NO, ATTACHMENT_ID)
    selection = service.get_report_sections(
        RCEPT_NO,
        ATTACHMENT_ID,
        section_kinds=("statements",),
    )

    assert listing.ok is True
    assert selection.ok is True
    for result in (listing, selection):
        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert warning.code is WarningCode.PARTIAL_COLLECTION
        assert warning.details["missing_sections"] == ["현금흐름표"]


def test_section_tools_refuse_data_that_failed_document_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = ParsedDocument(
        sections=(
            DocumentSection(
                title="재무상태표",
                kind=SectionKind.BALANCE_SHEET,
                blocks=(
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=(("계정", "당기"), ("자산총계",)),
                    ),
                ),
            ),
        ),
        source_sha256="c" * 64,
        source_type="xml",
        source_coverage=SourceCoverage(
            source_text_token_count=0,
            captured_text_token_count=0,
            source_text_sha256="d" * 64,
            captured_text_sha256="d" * 64,
            source_table_count=1,
            captured_table_count=1,
            source_cell_count=3,
            captured_cell_count=3,
            source_image_count=0,
            captured_image_count=0,
        ),
    )

    def load_malformed(
        _self: CrawlerService,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[LoadedDocument]:
        assert rcept_no == RCEPT_NO
        assert attachment_id == ATTACHMENT_ID
        return Result.success(
            LoadedDocument(
                document=malformed,
                attachment_title="별도감사보고서",
                source_rcept_no=RCEPT_NO,
            )
        )

    monkeypatch.setattr(CrawlerService, "_load_parsed_document", load_malformed)
    service = CrawlerService(SecretStr("test-key"), NetworkRejectingHttpClient())

    listing = service.list_report_sections(RCEPT_NO, ATTACHMENT_ID)
    selection = service.get_report_sections(
        RCEPT_NO,
        ATTACHMENT_ID,
        section_kinds=("statements",),
    )

    for result in (listing, selection):
        assert result.ok is False
        assert result.data is None
        assert result.error is not None
        assert result.error.code is ErrorCode.VALIDATION_FAILED
