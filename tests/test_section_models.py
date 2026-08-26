import pytest
from pydantic import ValidationError

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
    SourceCoverage,
)
from dart_crawler.document_validation import validate_document
from dart_crawler.query_limits import (
    LOCAL_QUERY_LIMITS,
    MAX_RESPONSE_CELLS,
    MAX_RESPONSE_TEXT_CHARS,
)
from dart_crawler.result import ErrorCode
from dart_crawler.section_models import (
    ReportSectionData,
    SectionBlock,
    SectionData,
    SectionSummary,
    TableData,
    missing_core_sections,
    returned_cell_count,
    returned_text_char_count,
    section_id,
    select_sections,
    summarize_sections,
)

_EXPECTED_SECTION_IDS = (
    "s001-opinion",
    "s002-balance_sheet",
    "s003-income",
    "s004-equity",
    "s005-cash_flow",
    "s006-note",
    "s007-note",
    "s008-note",
)
_EXPECTED_TOTAL_CELLS = 24


def _section(
    title: str,
    kind: SectionKind,
    blocks: tuple[DocumentBlock, ...],
) -> DocumentSection:
    return DocumentSection(title=title, kind=kind, blocks=blocks)


def _coverage() -> SourceCoverage:
    return SourceCoverage(
        source_text_token_count=0,
        captured_text_token_count=0,
        source_text_sha256="a" * 64,
        captured_text_sha256="a" * 64,
        source_table_count=7,
        captured_table_count=7,
        source_cell_count=24,
        captured_cell_count=24,
        source_image_count=1,
        captured_image_count=1,
    )


def _document(
    sections: tuple[DocumentSection, ...],
    *,
    coverage: SourceCoverage | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        sections=sections,
        source_sha256="b" * 64,
        source_type="xml",
        report_title=sections[0].title if sections else None,
        source_coverage=coverage,
    )


def _report() -> ParsedDocument:
    """Hand-built report: duplicate note titles and out-of-order note numbers."""
    return _document(
        (
            _section(
                "감사보고서",
                SectionKind.OPINION,
                (
                    DocumentBlock(BlockKind.HEADING, text="감사보고서"),
                    DocumentBlock(BlockKind.PARAGRAPH, text="적정의견을 표명합니다."),
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=(("구분", "내용"), ("의견", "적정")),
                    ),
                ),
            ),
            _section(
                "재무상태표",
                SectionKind.BALANCE_SHEET,
                (
                    DocumentBlock(BlockKind.HEADING, text="재무상태표"),
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=(("계정", "", ""), ("자산", "1,000", "900")),
                        merged_ranges=((1, 1, 1, 3),),
                    ),
                ),
            ),
            _section(
                "손익계산서",
                SectionKind.INCOME,
                (
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=(("매출", "100"), ("이익", "(10)")),
                    ),
                ),
            ),
            _section(
                "자본변동표",
                SectionKind.EQUITY,
                (DocumentBlock(BlockKind.TABLE, rows=(("자본", ""),)),),
            ),
            _section(
                "현금흐름표",
                SectionKind.CASH_FLOW,
                (DocumentBlock(BlockKind.TABLE, rows=(("현금", "6"),)),),
            ),
            _section(
                "주석 30",
                SectionKind.NOTE,
                (
                    DocumentBlock(BlockKind.PARAGRAPH, text="30. 현금흐름표"),
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=(("항목", "금액"), ("현금", "7")),
                    ),
                    DocumentBlock(BlockKind.IMAGE, image_source="note30.png"),
                ),
            ),
            _section(
                "주석 22",
                SectionKind.NOTE,
                (DocumentBlock(BlockKind.PARAGRAPH, text="22. 기타포괄손익누계액"),),
            ),
            _section(
                "주석 22",
                SectionKind.NOTE,
                (DocumentBlock(BlockKind.TABLE, rows=(("재고", "8"),)),),
            ),
        ),
        coverage=_coverage(),
    )


def _grid_document(row_count: int, column_count: int) -> ParsedDocument:
    return _document(
        (
            _section(
                "재무상태표",
                SectionKind.BALANCE_SHEET,
                (DocumentBlock(BlockKind.TABLE, rows=_grid_rows(row_count, column_count)),),
            ),
        )
    )


def _narrative_document(
    section_count: int,
    paragraph_chars: int,
    *,
    rows: tuple[tuple[str, ...], ...] = (),
) -> ParsedDocument:
    """Build notes whose weight is narrative text rather than table cells."""
    table = (DocumentBlock(BlockKind.TABLE, rows=rows),) if rows else ()
    return _document(
        tuple(
            _section(
                f"주석 {index + 1}",
                SectionKind.NOTE,
                (
                    DocumentBlock(BlockKind.PARAGRAPH, text="가" * paragraph_chars),
                    *table,
                ),
            )
            for index in range(section_count)
        )
    )


def _grid_rows(row_count: int, column_count: int) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(f"r{row}c{column}" for column in range(column_count))
        for row in range(row_count)
    )


def test_section_id_combines_source_order_with_the_kind_value() -> None:
    assert section_id(0, SectionKind.OPINION) == "s001-opinion"
    assert section_id(6, SectionKind.BALANCE_SHEET) == "s007-balance_sheet"
    assert section_id(22, SectionKind.NOTE) == "s023-note"


def test_summarize_sections_keeps_ids_unique_for_duplicate_and_unordered_titles() -> (
    None
):
    summaries = summarize_sections(_report())

    assert tuple(summary.section_id for summary in summaries) == _EXPECTED_SECTION_IDS
    assert [summary.title for summary in summaries[5:]] == [
        "주석 30",
        "주석 22",
        "주석 22",
    ]


def test_summarize_sections_counts_blocks_tables_and_images() -> None:
    summaries = summarize_sections(_report())

    opinion = summaries[0]
    assert opinion.kind is SectionKind.OPINION
    assert opinion.block_count == 3
    assert opinion.table_count == 1
    assert opinion.cell_count == 4
    assert opinion.has_image is False
    note_with_image = summaries[5]
    assert note_with_image.block_count == 3
    assert note_with_image.table_count == 1
    assert note_with_image.cell_count == 4
    assert note_with_image.has_image is True
    text_only_note = summaries[6]
    assert text_only_note.table_count == 0
    assert text_only_note.cell_count == 0


def test_summarize_sections_counts_narrative_characters_outside_tables() -> None:
    summaries = summarize_sections(_report())

    # 제목 5자 + 문단 12자, 표 셀은 cell_count가 이미 값을 매기므로 제외한다.
    assert summaries[0].text_char_count == 17
    assert summaries[1].text_char_count == len("재무상태표")
    # 표만 있는 구역은 서술 텍스트가 없다.
    assert summaries[2].text_char_count == 0
    # 문단 9자 + 표 0자 + 이미지 0자.
    assert summaries[5].text_char_count == 9


def test_summarize_sections_counts_empty_grid_slots_as_cells() -> None:
    summaries = summarize_sections(_report())

    # 재무상태표 첫 행은 병합으로 두 칸이 비어 있어도 6칸 전부를 센다.
    assert summaries[1].cell_count == 6
    assert summaries[3].cell_count == 2


def test_summary_cell_counts_reconcile_with_document_validation() -> None:
    document = _report()
    non_table_blocks = sum(
        1
        for section in document.sections
        for block in section.blocks
        if block.kind is not BlockKind.TABLE
    )

    validation = validate_document(document)
    summaries = summarize_sections(document)

    assert validation.ok is True
    assert validation.data is not None
    total_cells = sum(summary.cell_count for summary in summaries)
    assert total_cells == _EXPECTED_TOTAL_CELLS
    # validate_document counts one slot per non-table block on top of grid slots.
    assert validation.data.checked_cell_count == total_cells + non_table_blocks


def test_select_sections_requires_at_least_one_selector() -> None:
    result = select_sections(_report(), (), ())

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT


def test_select_sections_unions_both_selectors_in_document_order() -> None:
    result = select_sections(
        _report(),
        ("s005-cash_flow", "s002-balance_sheet"),
        ("income", "cash_flow"),
    )

    assert result.ok is True
    assert result.data is not None
    assert [section.section_id for section in result.data] == [
        "s002-balance_sheet",
        "s003-income",
        "s005-cash_flow",
    ]


def test_select_sections_deduplicates_a_section_named_by_both_selectors() -> None:
    result = select_sections(_report(), ("s002-balance_sheet",), ("balance_sheet",))

    assert result.ok is True
    assert result.data is not None
    assert [section.section_id for section in result.data] == ["s002-balance_sheet"]


def test_select_sections_expands_the_statements_alias_to_four_core_statements() -> None:
    result = select_sections(_report(), (), ("statements",))

    assert result.ok is True
    assert result.data is not None
    assert [section.kind for section in result.data] == [
        SectionKind.BALANCE_SHEET,
        SectionKind.INCOME,
        SectionKind.EQUITY,
        SectionKind.CASH_FLOW,
    ]


def test_select_sections_returns_every_section_of_a_repeated_kind() -> None:
    result = select_sections(_report(), (), ("note",))

    assert result.ok is True
    assert result.data is not None
    assert [section.section_id for section in result.data] == [
        "s006-note",
        "s007-note",
        "s008-note",
    ]


def test_select_sections_rejects_an_unknown_section_kind() -> None:
    result = select_sections(_report(), (), ("balance_sheet", "footnote"))

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["unknown_section_kinds"] == ["footnote"]


@pytest.mark.parametrize(
    "malformed",
    ["balance_sheet", "s1-opinion", "s001-unknown_kind", "s001", "S001-opinion", ""],
)
def test_select_sections_rejects_a_malformed_section_id(malformed: str) -> None:
    result = select_sections(_report(), (malformed,), ())

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["invalid_section_ids"] == [malformed]


def test_select_sections_reports_not_found_when_no_section_matches() -> None:
    result = select_sections(_report(), ("s099-note",), ())

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.next_action == "list_report_sections를 다시 호출해 최신 목차를 확인하세요."


def test_select_sections_reports_not_found_for_a_kind_absent_from_the_report() -> None:
    document = _document(
        (
            _section(
                "감사보고서",
                SectionKind.OPINION,
                (DocumentBlock(BlockKind.PARAGRAPH, text="의견"),),
            ),
        )
    )

    result = select_sections(document, (), ("statements",))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_select_sections_accepts_a_selection_at_the_cell_limit() -> None:
    result = select_sections(_grid_document(2000, 10), (), ("balance_sheet",))

    assert result.ok is True
    assert result.data is not None
    assert returned_cell_count(result.data) == MAX_RESPONSE_CELLS


def test_select_sections_rejects_a_selection_over_the_cell_limit_without_truncating() -> (
    None
):
    result = select_sections(_grid_document(2001, 10), (), ("balance_sheet",))

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["selected_cell_count"] == 20010
    assert result.error.details["limit"] == MAX_RESPONSE_CELLS


def test_select_sections_accepts_a_narrative_selection_at_the_text_limit() -> None:
    document = _narrative_document(20, MAX_RESPONSE_TEXT_CHARS // 20)

    result = select_sections(document, (), ("note",))

    assert result.ok is True
    assert result.data is not None
    assert returned_cell_count(result.data) == 0
    assert returned_text_char_count(result.data) == MAX_RESPONSE_TEXT_CHARS


def test_select_sections_rejects_a_narrative_selection_over_the_text_limit() -> None:
    """A notes-only selection carries no cells, so only the text guard sees it."""
    document = _narrative_document(20, MAX_RESPONSE_TEXT_CHARS // 20 + 1)

    result = select_sections(document, (), ("note",))

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["selected_text_char_count"] == MAX_RESPONSE_TEXT_CHARS + 20
    assert result.error.details["limit"] == MAX_RESPONSE_TEXT_CHARS
    assert result.error.details.get("selected_cell_count") is None
    assert result.next_action == "구역을 나누어 여러 번 호출하세요."


def test_select_sections_names_both_dimensions_when_both_limits_are_exceeded() -> None:
    """One rejection tells the caller everything they must split on."""
    document = _narrative_document(
        1,
        MAX_RESPONSE_TEXT_CHARS + 1,
        rows=_grid_rows(MAX_RESPONSE_CELLS // 10 + 1, 10),
    )

    result = select_sections(document, (), ("note",))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["selected_cell_count"] == MAX_RESPONSE_CELLS + 10
    assert result.error.details["limit"] == MAX_RESPONSE_CELLS
    assert result.error.details["selected_text_char_count"] == MAX_RESPONSE_TEXT_CHARS + 1
    assert result.error.details["text_char_limit"] == MAX_RESPONSE_TEXT_CHARS


def test_select_sections_accepts_over_remote_limits_with_local_limits() -> None:
    # Given
    document = _narrative_document(
        1,
        MAX_RESPONSE_TEXT_CHARS + 1,
        rows=_grid_rows(MAX_RESPONSE_CELLS // 10 + 1, 10),
    )

    # When
    result = select_sections(
        document,
        (),
        ("note",),
        limits=LOCAL_QUERY_LIMITS,
    )

    # Then
    assert result.ok is True
    assert result.data is not None
    assert returned_cell_count(result.data) == MAX_RESPONSE_CELLS + 10
    assert returned_text_char_count(result.data) == MAX_RESPONSE_TEXT_CHARS + 1


def test_select_sections_accepts_a_report_sized_mixed_selection() -> None:
    """A whole real report stays well inside both limits."""
    result = select_sections(_report(), (), ("statements", "note", "opinion"))

    assert result.ok is True
    assert result.data is not None
    assert returned_cell_count(result.data) < MAX_RESPONSE_CELLS
    assert returned_text_char_count(result.data) < MAX_RESPONSE_TEXT_CHARS


def test_returned_text_char_count_sums_only_non_table_text() -> None:
    result = select_sections(_report(), ("s001-opinion", "s006-note"), ())

    assert result.ok is True
    assert result.data is not None
    assert returned_text_char_count(result.data) == 17 + 9


def test_select_sections_copies_blocks_verbatim() -> None:
    result = select_sections(_report(), ("s002-balance_sheet", "s006-note"), ())

    assert result.ok is True
    assert result.data is not None
    balance_sheet, note = result.data
    assert balance_sheet.title == "재무상태표"
    assert balance_sheet.blocks[0] == SectionBlock(
        kind=BlockKind.HEADING, text="재무상태표"
    )
    assert balance_sheet.blocks[1].table == TableData(
        rows=(("계정", "", ""), ("자산", "1,000", "900")),
        merged_ranges=((1, 1, 1, 3),),
    )
    assert note.blocks[0].table is None
    assert note.blocks[0].text == "30. 현금흐름표"
    assert note.blocks[2].kind is BlockKind.IMAGE
    assert note.blocks[2].image_source == "note30.png"


def test_returned_cell_count_sums_only_table_slots() -> None:
    result = select_sections(_report(), (), ("statements",))

    assert result.ok is True
    assert result.data is not None
    assert returned_cell_count(result.data) == 14


def test_report_section_data_reports_both_size_counts() -> None:
    """The data response prices both axes, as the table of contents does."""
    result = select_sections(_report(), ("s001-opinion",), ())
    assert result.ok is True
    assert result.data is not None

    payload = ReportSectionData(
        rcept_no="20260515001658",
        attachment_id="opendart:20260515001658:audit.xml",
        source_sha256="b" * 64,
        parser_version="0.1.0",
        returned_cell_count=returned_cell_count(result.data),
        returned_text_char_count=returned_text_char_count(result.data),
        sections=result.data,
    )

    assert payload.returned_cell_count == 4
    assert payload.returned_text_char_count == 17


def test_report_section_data_requires_the_narrative_count() -> None:
    result = select_sections(_report(), ("s001-opinion",), ())
    assert result.data is not None

    with pytest.raises(ValidationError):
        ReportSectionData(  # type: ignore[call-arg]
            rcept_no="20260515001658",
            attachment_id="opendart:20260515001658:audit.xml",
            source_sha256="b" * 64,
            parser_version="0.1.0",
            returned_cell_count=4,
            sections=result.data,
        )


def test_section_models_serialize_enums_as_plain_strings() -> None:
    section = SectionData(
        section_id="s002-balance_sheet",
        title="재무상태표",
        kind=SectionKind.BALANCE_SHEET,
        blocks=(
            SectionBlock(kind=BlockKind.TABLE, table=TableData(rows=(("자산", "1"),))),
        ),
    )

    payload = section.model_dump_json()

    assert '"kind":"balance_sheet"' in payload
    assert '"kind":"table"' in payload


def test_section_models_are_frozen_and_reject_unknown_fields() -> None:
    summary = SectionSummary(
        section_id="s001-opinion",
        title="감사보고서",
        kind=SectionKind.OPINION,
        block_count=1,
        table_count=0,
        cell_count=0,
        text_char_count=0,
        has_image=False,
    )

    with pytest.raises(ValidationError):
        summary.title = "다른 제목"
    with pytest.raises(ValidationError):
        TableData(rows=(), section_count=1)  # type: ignore[call-arg]


def test_missing_core_sections_returns_nothing_for_a_complete_report() -> None:
    assert missing_core_sections(_report()) == ()


def test_missing_core_sections_lists_every_absent_statement() -> None:
    document = _document(
        (
            _section(
                "감사보고서",
                SectionKind.OPINION,
                (DocumentBlock(BlockKind.PARAGRAPH, text="의견"),),
            ),
        )
    )

    assert missing_core_sections(document) == (
        "재무상태표",
        "손익·포괄손익",
        "자본변동표",
        "현금흐름표",
    )


def test_missing_core_sections_ignores_a_statement_section_without_a_table() -> None:
    document = _document(
        (
            _section(
                "재무상태표",
                SectionKind.BALANCE_SHEET,
                (DocumentBlock(BlockKind.PARAGRAPH, text="첨부를 참조하시기 바랍니다."),),
            ),
        )
    )

    assert "재무상태표" in missing_core_sections(document)
