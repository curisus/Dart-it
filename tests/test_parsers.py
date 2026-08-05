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
