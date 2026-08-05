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
