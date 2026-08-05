from pathlib import Path

from openpyxl import load_workbook

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
)
from dart_crawler.excel_export import ExcelExportService, ExportContext
from dart_crawler.value_parser import parse_cell_value


def _document(*, include_image: bool = False) -> ParsedDocument:
    sections = [
        DocumentSection(
            title="재무상태표",
            kind=SectionKind.BALANCE_SHEET,
            blocks=(
                DocumentBlock(
                    BlockKind.TABLE,
                    rows=(("계정", "당기"), ("자산", "1,000")),
                    merged_ranges=((1, 1, 1, 2),),
                ),
            ),
        ),
        DocumentSection(
            title="손익 및 포괄손익계산서",
            kind=SectionKind.INCOME,
            blocks=(DocumentBlock(BlockKind.TABLE, rows=(("매출", "(10)"),)),),
        ),
        DocumentSection(
            title="자본변동표",
            kind=SectionKind.EQUITY,
            blocks=(DocumentBlock(BlockKind.TABLE, rows=(("자본", "5"),)),),
        ),
        DocumentSection(
            title="현금흐름표",
            kind=SectionKind.CASH_FLOW,
            blocks=(DocumentBlock(BlockKind.TABLE, rows=(("현금", "6"),)),),
        ),
    ]
    if include_image:
        sections.append(
            DocumentSection(
                title="주석 1",
                kind=SectionKind.NOTE,
                blocks=(DocumentBlock(BlockKind.IMAGE, image_source="note.png"),),
            )
        )
    return ParsedDocument(
        sections=tuple(sections),
        source_sha256="a" * 64,
        source_type="xml",
    )


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
    assert parse_cell_value("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert parse_cell_value("천원", unit_multiplier=1000) == "천원"


def test_export_writes_metadata_first_and_marks_image_only_notes_partial(
    tmp_path: Path,
) -> None:
    result = ExcelExportService(tmp_path).export(
        _context(_document(include_image=True))
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.collection_status == "partial"
    assert result.data.output_path.exists()
    assert result.data.output_path.name.endswith("_부분수집.xlsx")
    assert result.data.output_path.stat().st_size > 0
    workbook = load_workbook(result.data.output_path)
    assert "A1:B1" in {str(item) for item in workbook["재무상태표"].merged_cells.ranges}
    workbook.close()


def test_export_does_not_write_when_core_statement_is_missing(tmp_path: Path) -> None:
    document = ParsedDocument(
        sections=(
            DocumentSection(
                title="주석 1",
                kind=SectionKind.NOTE,
                blocks=(DocumentBlock(BlockKind.TABLE, rows=(("내용", "값"),)),),
            ),
        ),
        source_sha256="b" * 64,
        source_type="xml",
    )

    result = ExcelExportService(tmp_path).export(_context(document))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "CORE_STATEMENT_MISSING"
    assert list(tmp_path.glob("*.xlsx")) == []
