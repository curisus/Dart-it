from dart_crawler.document_model import BlockKind, SectionKind
from dart_crawler.html_parser import parse_html_document
from dart_crawler.xml_parser import parse_xml_document


def test_xml_parser_preserves_table_order_and_image_placeholder() -> None:
    xml = """<document>
      <heading>재무상태표</heading>
      <table><tr><td>계정</td><td>금액</td></tr><tr><td>자산</td><td>100</td></tr></table>
      <img src="image-1.png" />
    </document>""".encode()

    result = parse_xml_document(xml)

    assert result.ok is True
    assert result.data is not None
    assert result.data.sections[0].kind is SectionKind.BALANCE_SHEET
    assert [block.kind for block in result.data.sections[0].blocks] == [
        BlockKind.HEADING,
        BlockKind.TABLE,
        BlockKind.IMAGE,
    ]
    assert result.data.sections[0].blocks[1].rows[1] == ("자산", "100")


def test_html_parser_preserves_all_visible_non_image_content() -> None:
    html = b"""
    <document>
      <company-name>Sample Corp</company-name>
      <table><tr><tu>2025-01-01</tu><td>100</td></tr></table>
      <img-caption>Control description</img-caption>
      <extraction>internal-id</extraction>
    </document>
    """

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.kind for block in blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.TABLE,
        BlockKind.PARAGRAPH,
    ]
    assert blocks[0].text == "Sample Corp"
    assert blocks[1].rows == (("2025-01-01", "100"),)
    assert blocks[2].text == "Control description"


def test_html_parser_marks_all_image_tags_without_filename_text() -> None:
    html = b"""
    <document>
      <p>Visible</p>
      <img src="first.jpg" />
      <image src="second.jpg">second.jpg</image>
    </document>
    """

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.kind for block in blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.IMAGE,
        BlockKind.IMAGE,
    ]


def test_html_parser_preserves_caption_inside_image_container() -> None:
    html = (
        b"<image><img>figure.jpg</img>"
        b"<img-caption>Visible control description</img-caption></image>"
    )

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.kind for block in blocks] == [
        BlockKind.IMAGE,
        BlockKind.PARAGRAPH,
    ]
    assert blocks[1].text == "Visible control description"
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True
    assert coverage.source_image_count == 1
    assert coverage.source_text_token_count == 3


def test_html_parser_records_complete_source_coverage() -> None:
    html = b"""
    <document>
      <p>Alpha beta</p>
      <table><tr><tu>2025</tu><td>100</td></tr></table>
      <img src="first.jpg" />
      <image src="second.jpg">second.jpg</image>
    </document>
    """

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True
    assert coverage.source_text_token_count == 4
    assert coverage.captured_text_token_count == 4
    assert coverage.source_table_count == 1
    assert coverage.captured_table_count == 1
    assert coverage.source_cell_count == 2
    assert coverage.captured_cell_count == 2
    assert coverage.source_image_count == 2
    assert coverage.captured_image_count == 2


def test_html_parser_places_rowspan_cells_before_following_columns() -> None:
    html = b"""
    <table>
      <tr><th rowspan="2">A</th><th colspan="2">B</th></tr>
      <tr><td>C</td><td>D</td></tr>
    </table>
    """

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    table = result.data.sections[0].blocks[0]
    assert table.rows == (("A", "B", ""), ("", "C", "D"))
    assert table.merged_ranges == ((1, 1, 2, 1), (1, 2, 1, 3))


def test_xml_parser_places_rowspan_cells_before_following_columns() -> None:
    xml = b"""
    <table>
      <tr><th rowspan="2">A</th><th colspan="2">B</th></tr>
      <tr><td>C</td><td>D</td></tr>
    </table>
    """

    result = parse_xml_document(xml)

    assert result.ok is True
    assert result.data is not None
    table = result.data.sections[0].blocks[0]
    assert table.rows == (("A", "B", ""), ("", "C", "D"))
    assert table.merged_ranges == ((1, 1, 2, 1), (1, 2, 1, 3))


def test_xml_parser_keeps_second_header_row_between_side_rowspans() -> None:
    xml = b"""
    <table>
      <tr>
        <th rowspan="2">G</th><th rowspan="2">N</th>
        <th colspan="4">O</th>
        <th rowspan="2">I</th><th rowspan="2">T</th>
      </tr>
      <tr><th>M1</th><th>M2</th><th>M3</th><th>M4</th></tr>
      <tr>
        <td>R</td><td>1</td><td>2</td><td>3</td>
        <td>4</td><td>5</td><td>6</td><td>7</td>
      </tr>
    </table>
    """

    result = parse_xml_document(xml)

    assert result.ok is True
    assert result.data is not None
    table = result.data.sections[0].blocks[0]
    assert table.rows == (
        ("G", "N", "O", "", "", "", "I", "T"),
        ("", "", "M1", "M2", "M3", "M4", "", ""),
        ("R", "1", "2", "3", "4", "5", "6", "7"),
    )
    assert table.merged_ranges == (
        (1, 1, 2, 1),
        (1, 2, 2, 2),
        (1, 3, 1, 6),
        (1, 7, 2, 7),
        (1, 8, 2, 8),
    )


def test_xml_parser_preserves_same_visible_content_as_html() -> None:
    xml = b"""
    <document>
      <company-name>Sample Corp</company-name>
      <table><tr><tu>2025-12-31</tu><td>200</td></tr></table>
      <img-caption>Control description</img-caption>
      <extraction>internal-id</extraction>
    </document>
    """

    result = parse_xml_document(xml)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.kind for block in blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.TABLE,
        BlockKind.PARAGRAPH,
    ]
    assert blocks[0].text == "Sample Corp"
    assert blocks[1].rows == (("2025-12-31", "200"),)
    assert blocks[2].text == "Control description"


def test_xml_parser_reports_safe_fallback_for_malformed_xml() -> None:
    xml = b"<document><p>Visible</p><broken></document>"

    result = parse_xml_document(xml)

    assert result.ok is True
    assert result.data is not None
    assert result.data.sections[0].blocks[0].text == "Visible"
    assert [warning.code.value for warning in result.warnings] == [
        "FALLBACK_SOURCE_USED"
    ]


def test_xml_parser_preserves_cdata_and_includes_it_in_coverage() -> None:
    xml = (
        b"<document><heading>Visible heading</heading>"
        b"<![CDATA[Visible CDATA body]]></document>"
    )

    result = parse_xml_document(xml)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "Visible heading"),
        (BlockKind.PARAGRAPH, "Visible CDATA body"),
    ]
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True
    assert coverage.source_text_token_count == 5


def test_html_parser_preserves_leading_indentation_in_text_blocks() -> None:
    html = (
        "<document>"
        "<p>   들여쓴 문단</p>"
        "<p>\u00a0\u00a0비분리공백 들여쓰기</p>"
        "<heading>  들여쓴 제목</heading>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    first_blocks = result.data.sections[0].blocks
    assert first_blocks[0].text == "   들여쓴 문단"
    assert first_blocks[1].text == "\u00a0\u00a0비분리공백 들여쓰기"
    heading_section = result.data.sections[1]
    assert heading_section.title == "들여쓴 제목"
    assert heading_section.blocks[0].kind is BlockKind.HEADING
    assert heading_section.blocks[0].text == "  들여쓴 제목"


def test_html_parser_keeps_blank_paragraphs_as_blank_line_blocks() -> None:
    html = (
        "<document>"
        "<p>첫 문단</p>"
        "<p></p>"
        "<p> </p>"
        "<p>\u00a0</p>"
        "<p>마지막 문단</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, "첫 문단"),
        (BlockKind.PARAGRAPH, ""),
        (BlockKind.PARAGRAPH, ""),
        (BlockKind.PARAGRAPH, ""),
        (BlockKind.PARAGRAPH, "마지막 문단"),
    ]
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True


def test_html_parser_skips_blank_paragraphs_before_first_content() -> None:
    html = b"<document><p></p><p>Body</p></document>"

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, "Body"),
    ]


def test_html_parser_preserves_leading_indentation_in_table_cells() -> None:
    html = "<table><tr><td>   1. 현금및현금성자산</td><td>1,000</td></tr></table>".encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    table = result.data.sections[0].blocks[0]
    assert table.rows == (("   1. 현금및현금성자산", "1,000"),)


def test_html_parser_does_not_emit_blank_blocks_for_paragraphs_inside_tables() -> None:
    html = (
        b"<table>"
        b"<p>table caption</p>"
        b"<tr><td><p>cell text</p><p></p></td><td>2</td></tr>"
        b"</table>"
    )

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.kind for block in blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.TABLE,
    ]
    assert blocks[0].text == "table caption"
    assert blocks[1].rows == (("cell text", "2"),)


def test_html_parser_ignores_markup_newline_indentation() -> None:
    html = b"<document><p>\n      Wrapped markup line</p></document>"

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert result.data.sections[0].blocks[0].text == "Wrapped markup line"


def test_html_parser_does_not_invent_indentation_from_markup_gaps() -> None:
    html = (
        "<document>"
        "<p>\u3000\u3000<span>당사는</span></p>"
        "<table><tr><td> <p>매출액</p> </td><td>10</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert blocks[0].text == "\u3000\u3000당사는"
    assert blocks[1].rows == ((" 매출액", "10"),)


def test_html_parser_keeps_author_indentation_after_markup_newline() -> None:
    html = "<document><p>\n\u3000\u3000당사는 다음과 같습니다.\n</p></document>".encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert result.data.sections[0].blocks[0].text == "\u3000\u3000당사는 다음과 같습니다."


def test_html_parser_does_not_emit_blank_for_image_only_paragraph() -> None:
    html = b'<document><p>Body</p><p><img src="a.png"/></p></document>'

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, "Body"),
        (BlockKind.IMAGE, ""),
    ]


def test_note_sections_split_on_indented_note_headings() -> None:
    html = (
        "<document>"
        "<heading>주석</heading>"
        "<p> 1. 일반사항</p>"
        "<p>내용</p>"
        "<p> 2. 중요한 회계처리방침</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    titles = [section.title for section in result.data.sections]
    assert "주석 1" in titles
    assert "주석 2" in titles


_INCOME_STATEMENT = (
    "<table><tr><td>손익계산서</td><td>제 5 기</td></tr>"
    "<tr><td>매출액</td><td>100</td></tr></table>"
)


def test_note_sections_keep_statement_titled_tables_in_one_sheet() -> None:
    html = (
        "<document>"
        "<p>감사보고서</p>" + _INCOME_STATEMENT + "<heading>주석</heading>"
        "<p>34. 특수관계자</p>"
        "<p>(4) 수령한 배당내역은 다음과 같습니다.</p>"
        "<table><tr><td>(주1)</td>"
        "<td>배당금수익은 포괄손익계산서상 매출액으로 표시하고 있습니다.</td></tr></table>"
        "<p>(5) 지급한 배당내역은 다음과 같습니다.</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    titles = [section.title for section in result.data.sections]
    assert titles == ["본문", "손익계산서", "주석", "주석 34"]
    note_section = result.data.sections[3]
    assert [block.kind for block in note_section.blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.PARAGRAPH,
        BlockKind.TABLE,
        BlockKind.PARAGRAPH,
    ]


def test_note_sections_keep_statement_headings_in_one_sheet() -> None:
    html = (
        "<document>"
        "<p>감사보고서</p>" + _INCOME_STATEMENT + "<heading>주석</heading>"
        "<p>34. 특수관계자</p>"
        "<heading>손익계산서</heading>"
        "<p>이어지는 주석 본문입니다.</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    titles = [section.title for section in result.data.sections]
    assert titles == ["본문", "손익계산서", "주석", "주석 34"]
    assert len(result.data.sections[3].blocks) == 3


def test_first_statement_inside_a_note_titled_section_still_opens_its_sheet() -> None:
    html = (
        "<document>"
        "<heading>(첨부)재무제표 및 주석</heading>"
        "<p>다음은 재무제표입니다.</p>"
        "<table><tr><td>재무상태표</td><td>제 5 기</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        + _INCOME_STATEMENT
        + "<table><tr><td>자본변동표</td><td>제 5 기</td></tr>"
        "<tr><td>자본총계</td><td>100</td></tr></table>"
        "<table><tr><td>현금흐름표</td><td>제 5 기</td></tr>"
        "<tr><td>현금성자산</td><td>100</td></tr></table>"
        "<p>1. 일반사항</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    kinds = {section.kind for section in result.data.sections}
    assert SectionKind.BALANCE_SHEET in kinds
    assert SectionKind.INCOME in kinds
    assert SectionKind.EQUITY in kinds
    assert SectionKind.CASH_FLOW in kinds


def test_standalone_statement_title_lines_open_their_own_sections() -> None:
    html = (
        "<document>"
        "<heading>(첨부)재 무 제 표</heading>"
        "<p>현대자동차주식회사</p>"
        "<p>재 무 상 태 표</p>"
        "<table><tr><td>과 목</td><td>제58기말</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "<p>손 익 계 산 서</p>"
        "<table><tr><td>과 목</td><td>제58기</td></tr>"
        "<tr><td>매출액</td><td>100</td></tr></table>"
        "<p>자 본 변 동 표</p>"
        "<table><tr><td>과 목</td><td>제58기</td></tr>"
        "<tr><td>자본총계</td><td>100</td></tr></table>"
        "<p>현 금 흐 름 표</p>"
        "<table><tr><td>과 목</td><td>제58기</td></tr>"
        "<tr><td>현금성자산</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    kinds = {section.kind for section in result.data.sections}
    assert {
        SectionKind.BALANCE_SHEET,
        SectionKind.INCOME,
        SectionKind.EQUITY,
        SectionKind.CASH_FLOW,
    } <= kinds
    for kind in (
        SectionKind.BALANCE_SHEET,
        SectionKind.INCOME,
        SectionKind.EQUITY,
        SectionKind.CASH_FLOW,
    ):
        assert any(
            block.kind is BlockKind.TABLE
            for section in result.data.sections
            if section.kind is kind
            for block in section.blocks
        )


def test_consolidated_statement_title_line_opens_its_section() -> None:
    html = (
        "<document>"
        "<heading>(첨부)연 결 재 무 제 표</heading>"
        "<p>연 결 재 무 상 태 표</p>"
        "<table><tr><td>과 목</td><td>제58기말</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert any(
        section.kind is SectionKind.BALANCE_SHEET
        for section in result.data.sections
    )


def test_statement_title_lines_without_a_table_do_not_open_sections() -> None:
    html = (
        "<document>"
        "<heading>목 차</heading>"
        "<p>재 무 상 태 표</p>"
        "<p>포 괄 손 익 계 산 서</p>"
        "<p>자 본 변 동 표</p>"
        "<p>현 금 흐 름 표</p>"
        "<p>주 석</p>"
        "<heading>(첨부)재 무 제 표</heading>"
        "<table><tr><td>재 무 상 태 표</td><td>제58기말</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    titles = [section.title for section in result.data.sections]
    assert titles == ["목 차", "(첨부)재 무 제 표", "재무상태표"]


def test_listed_statement_titles_open_no_section_except_beside_a_table() -> None:
    """A listed title yields to the next title; only one beside a table opens.

    Suppressing that last entry too would need the line before it, and a
    running header repeating one title would then lose its statement, which
    costs the whole file instead of one sheet.
    """
    html = (
        "<document>"
        "<heading>목 차</heading>"
        "<p>재 무 상 태 표</p>"
        "<p>포 괄 손 익 계 산 서</p>"
        "<p>자 본 변 동 표</p>"
        "<table><tr><td>구 분</td><td>쪽</td></tr>"
        "<tr><td>재무제표</td><td>1</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert [section.title for section in result.data.sections] == [
        "목 차",
        "자본변동표",
    ]


def test_repeated_statement_title_keeps_opening_its_section() -> None:
    html = (
        "<document>"
        "<heading>(첨부)재 무 제 표</heading>"
        "<p>재 무 상 태 표</p>"
        "<p></p>"
        "<p>재 무 상 태 표</p>"
        "<table><tr><td>과 목</td><td>제58기말</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert any(
        block.kind is BlockKind.TABLE
        for section in result.data.sections
        if section.kind is SectionKind.BALANCE_SHEET
        for block in section.blocks
    )


def test_statement_title_line_opens_a_section_across_caption_lines() -> None:
    html = (
        "<document>"
        "<heading>(첨부)재 무 제 표</heading>"
        "<p>재 무 상 태 표</p>"
        "<p>제 58 기 2025년 12월 31일 현재</p>"
        "<p>주식회사 예시</p>"
        "<p>(단위: 백만원)</p>"
        "<table><tr><td>과 목</td><td>제58기말</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert [section.title for section in result.data.sections] == [
        "(첨부)재 무 제 표",
        "재무상태표",
    ]


def test_statement_title_line_opens_a_section_across_a_blank_line() -> None:
    html = (
        "<document>"
        "<heading>(첨부)재 무 제 표</heading>"
        "<p>현대자동차주식회사</p>"
        "<p>재 무 상 태 표</p>"
        "<p></p>"
        "<table><tr><td>과 목</td><td>제58기말</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert [section.title for section in result.data.sections] == [
        "(첨부)재 무 제 표",
        "재무상태표",
    ]


def test_table_title_is_read_from_the_first_three_rows() -> None:
    html = (
        "<document>"
        "<p>감사보고서</p>"
        "<table>"
        "<tr><td>주식회사 예시</td></tr>"
        "<tr><td>제 5 기</td></tr>"
        "<tr><td>현 금 흐 름 표</td></tr>"
        "<tr><td>영업활동현금흐름</td><td>100</td></tr>"
        "</table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert [section.title for section in result.data.sections] == [
        "본문",
        "현금흐름표",
    ]


def test_comprehensive_income_table_keeps_the_income_statement_title() -> None:
    html = (
        "<document>"
        "<p>감사보고서</p>"
        "<table><tr><td>연 결 포 괄 손 익 계 산 서</td><td>제 5 기</td></tr>"
        "<tr><td>매출액</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert [section.title for section in result.data.sections] == [
        "본문",
        "손익계산서",
    ]


def test_numbered_note_titles_do_not_open_statement_sections() -> None:
    html = (
        "<document>"
        "<heading>주석</heading>"
        "<p>30. 현금흐름표</p>"
        "<p>(3) 요약연결현금흐름표</p>"
        "<table><tr><td>구 분</td><td>당기</td></tr>"
        "<tr><td>영업활동</td><td>100</td></tr></table>"
        "<p>22. 기타포괄손익누계액</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    titles = [section.title for section in result.data.sections]
    assert titles == ["주석", "주석 30", "주석 22"]


def test_table_less_statement_title_does_not_suppress_the_real_statement() -> None:
    html = (
        "<document>"
        "<heading>재무상태표</heading>"
        "<p>재무상태표는 첨부를 참조하시기 바랍니다.</p>"
        "<heading>주석</heading>"
        "<p>1. 회사의 개요</p>"
        "<table><tr><td>재무상태표</td><td>제 5 기</td></tr>"
        "<tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    assert any(
        block.kind is BlockKind.TABLE
        for section in result.data.sections
        if section.kind is SectionKind.BALANCE_SHEET
        for block in section.blocks
    )


def test_first_statement_heading_after_note_body_still_opens_its_sheet() -> None:
    html = (
        "<document>"
        "<heading>주석</heading>"
        "<p>1. 일반사항</p>"
        "<heading>재무상태표</heading>"
        "<table><tr><td>자산총계</td><td>100</td></tr></table>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    kinds = {section.kind for section in result.data.sections}
    assert SectionKind.BALANCE_SHEET in kinds


def test_note_paragraph_splits_rows_at_title_and_item_markers() -> None:
    html = (
        "<document>"
        '<p><span usermark="B">41. 중단영업</span>(1) 중단영업의 내용연결실체는 '
        "매각을 결정하였습니다.(2) 표시된 내역은 다음과 같습니다.</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, "41. 중단영업"),
        (BlockKind.PARAGRAPH, "(1) 중단영업의 내용연결실체는 매각을 결정하였습니다."),
        (BlockKind.PARAGRAPH, "(2) 표시된 내역은 다음과 같습니다."),
    ]
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True


def test_paragraph_keeps_trailing_bare_item_marker_with_its_sentence() -> None:
    html = (
        "<document>"
        '<p><span usermark="B">41. 중단영업</span>(1) 매각을 결정하였습니다.(2)</p>'
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.text for block in blocks] == [
        "41. 중단영업",
        "(1) 매각을 결정하였습니다.(2)",
    ]
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True


def test_paragraph_keeps_mid_sentence_enumeration_in_one_row() -> None:
    html = (
        "<document>"
        "<p>회사의 내부회계관리제도는 (1) 자산의 거래와 처분을 반영하는 기록을 유지하고 "
        "(2) 재무제표가 작성되도록 거래를 기록하며 (3) 자산의 취득을 예방합니다.</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert len(blocks) == 1
    assert blocks[0].text.startswith("회사의 내부회계관리제도는 (1) 자산의")


def test_paragraph_keeps_parenthesized_number_attached_to_word() -> None:
    html = (
        "<document>"
        "<p>1. 배출권 무상할당 배출권은 영(0)으로 측정하여 인식하고 있습니다.</p>"
        "</document>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert [block.text for block in blocks] == [
        "1. 배출권 무상할당 배출권은 영(0)으로 측정하여 인식하고 있습니다.",
    ]


def test_source_coverage_matches_for_item_marker_glued_inside_table_cell() -> None:
    html = (
        "<table><tr>"
        "<td>발행일 이후 매 분기별 지급합니다.(2) 이자지급 조건</td>"
        "<td>10</td>"
        "</tr></table>"
    ).encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    table = result.data.sections[0].blocks[0]
    assert table.rows == (("발행일 이후 매 분기별 지급합니다.(2) 이자지급 조건", "10"),)
    coverage = result.data.source_coverage
    assert coverage is not None
    assert coverage.complete is True


def test_html_parser_uses_same_document_block_shape() -> None:
    html = """
    <html><body>
      <h2>현금흐름표</h2>
      <table><tr><th colspan="2">항목</th></tr><tr><td>현금</td><td>(10)</td></tr></table>
      <p>본문</p><img src="figure.png" />
    </body></html>
    """.encode()

    result = parse_html_document(html)

    assert result.ok is True
    assert result.data is not None
    blocks = result.data.sections[0].blocks
    assert result.data.sections[0].kind is SectionKind.CASH_FLOW
    assert [block.kind for block in blocks] == [
        BlockKind.HEADING,
        BlockKind.TABLE,
        BlockKind.PARAGRAPH,
        BlockKind.IMAGE,
    ]
    assert blocks[1].rows[0] == ("항목", "")
    assert blocks[1].merged_ranges == ((1, 1, 1, 2),)
