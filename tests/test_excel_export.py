from dataclasses import replace
from pathlib import Path

from openpyxl import load_workbook

from dart_crawler.document_model import ParsedDocument
from dart_crawler.excel_export import ExcelExportService, ExportContext
from dart_crawler.value_parser import parse_cell_value
from dart_crawler.xml_parser import parse_xml_document


def _parse_document(markup: str) -> ParsedDocument:
    result = parse_xml_document(markup.encode())
    assert result.ok is True
    assert result.data is not None
    return result.data


def _document(*, include_image: bool = False) -> ParsedDocument:
    parts = [
        "<document>",
        "<heading>재무상태표</heading>",
        '<table><tr><td colspan="2">계정</td></tr>',
        "<tr><td>자산</td><td>1,000</td></tr></table>",
        "<heading>손익 및 포괄손익계산서</heading>",
        "<table><tr><td>매출</td><td>(10)</td></tr></table>",
        "<heading>자본변동표</heading>",
        "<table><tr><td>자본</td><td>5</td></tr></table>",
        "<heading>현금흐름표</heading>",
        "<table><tr><td>현금</td><td>6</td></tr></table>",
    ]
    if include_image:
        parts.extend(
            [
                "<heading>주석 1</heading>",
                "<image><img>note.png</img>",
                "<img-caption>이미지 설명문</img-caption></image>",
            ]
        )
    parts.append("</document>")
    return _parse_document("".join(parts))


def _context(document: ParsedDocument) -> ExportContext:
    return ExportContext(
        company_name="Sample Company",
        report_date="2026-03-10",
        report_title="감사보고서",
        receipt_date="20260310",
        rcept_no="20260310002820",
        attachment_id="opendart:20260310002820:audit.xml",
        correction_chain=("20260310002820",),
        source_url="https://dart.example/report",
        parser_version="0.1.0",
        document=document,
    )


def test_value_parser_handles_commas_parentheses_and_formula_text() -> None:
    assert parse_cell_value("1,000") == 1000
    assert parse_cell_value("(10)") == -10
    assert parse_cell_value("-") == "-"
    assert parse_cell_value("- 투자") == "- 투자"
    assert parse_cell_value("-SUM(A1:A2)") == "'-SUM(A1:A2)"
    assert parse_cell_value("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert parse_cell_value("천원", unit_multiplier=1000) == "천원"


def test_value_parser_preserves_leading_indentation_for_text() -> None:
    assert parse_cell_value("   1. 현금및현금성자산") == "   1. 현금및현금성자산"
    assert parse_cell_value("\u00a0\u00a0계정") == "\u00a0\u00a0계정"
    assert parse_cell_value("   1,000") == 1000
    assert parse_cell_value("   ") == ""
    assert parse_cell_value("들여쓰기없음  ") == "들여쓰기없음"
    assert parse_cell_value(" =SUM(A1:A2)") == " =SUM(A1:A2)"


def test_export_preserves_blank_lines_and_indentation(tmp_path: Path) -> None:
    document = _parse_document(
        "<document>"
        "<heading>재무상태표</heading>"
        "<table><tr><td>   1. 현금및현금성자산</td><td>1,000</td></tr></table>"
        "<heading>손익 및 포괄손익계산서</heading>"
        "<table><tr><td>매출</td><td>(10)</td></tr></table>"
        "<heading>자본변동표</heading>"
        "<table><tr><td>자본</td><td>5</td></tr></table>"
        "<heading>현금흐름표</heading>"
        "<table><tr><td>현금</td><td>6</td></tr></table>"
        "<p>영업활동 설명</p>"
        "<p></p>"
        "<p>   들여쓴 문단</p>"
        "</document>"
    )

    result = ExcelExportService(tmp_path).export(_context(document))

    assert result.ok is True
    assert result.data is not None
    workbook = load_workbook(result.data.output_path)
    balance_sheet = workbook["재무상태표"]
    assert balance_sheet["A2"].value == "   1. 현금및현금성자산"
    cash_flow = workbook["현금흐름표"]
    assert cash_flow["A3"].value == "영업활동 설명"
    assert cash_flow["A4"].value is None
    assert cash_flow["A5"].value == "   들여쓴 문단"
    workbook.close()


def test_export_writes_metadata_and_marks_mixed_image_section_partial(
    tmp_path: Path,
) -> None:
    result = ExcelExportService(tmp_path).export(
        _context(_document(include_image=True))
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.collection_status == "partial"
    assert result.data.validation_status == "passed"
    assert result.data.validated_cell_count > 0
    assert result.data.validated_merge_count > 0
    assert result.data.output_path.exists()
    assert result.data.output_path.name.endswith("_부분수집.xlsx")
    assert result.data.output_path.stat().st_size > 0
    workbook = load_workbook(result.data.output_path)
    assert "A2:B2" in {str(item) for item in workbook["재무상태표"].merged_cells.ranges}
    metadata = {
        str(row[0].value): str(row[1].value)
        for row in workbook["수집정보"].iter_rows(min_col=1, max_col=2)
        if row[0].value is not None and row[1].value is not None
    }
    assert metadata["source_coverage_status"] == "passed"
    assert metadata["source_cell_count"] == metadata["captured_cell_count"]
    assert metadata["source_table_count"] == metadata["captured_table_count"]
    assert metadata["source_image_count"] == metadata["captured_image_count"]
    assert "주석 1:부분수집" in metadata["section_statuses"]
    workbook.close()


def test_export_does_not_write_when_core_statement_is_missing(tmp_path: Path) -> None:
    document = _parse_document(
        "<document><heading>주석 1</heading>"
        "<table><tr><td>내용</td><td>값</td></tr></table></document>"
    )

    result = ExcelExportService(tmp_path).export(_context(document))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "CORE_STATEMENT_MISSING"
    assert list(tmp_path.glob("*.xlsx")) == []


def test_export_rejects_document_without_source_coverage(tmp_path: Path) -> None:
    document = replace(_document(), source_coverage=None)

    result = ExcelExportService(tmp_path).export(_context(document))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "VALIDATION_FAILED"
    assert result.error.details["issue"] == "source_coverage_missing"
    assert list(tmp_path.glob("*.xlsx")) == []
