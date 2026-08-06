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
