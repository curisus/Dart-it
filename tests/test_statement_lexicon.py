from typing import Final

import pytest

from dart_crawler import attachments, document_model, excel_export
from dart_crawler.document_model import BlockKind, DocumentBlock, SectionKind
from dart_crawler.html_parser import parse_html_document
from dart_crawler.statement_lexicon import (
    classify,
    compact,
    statement_title_in_rows,
    statement_title_of_line,
)

COMPACT_CASES: Final[tuple[tuple[str, str], ...]] = (
    ("재 무 상 태 표", "재무상태표"),
    ("재\t무\t상\t태\t표", "재무상태표"),
    ("재\u00a0무\u00a0상\u00a0태\u00a0표", "재무상태표"),
    ("재\u3000무\u3000상\u3000태\u3000표", "재무상태표"),
    (" \t재\u00a0무\u3000상 태 표\t", "재무상태표"),
)

STATEMENT_TITLE_OF_LINE_CASES: Final[tuple[tuple[str, str | None], ...]] = (
    ("재무상태표", "재무상태표"),
    ("재 무 상 태 표", "재무상태표"),
    ("연결재무상태표", "재무상태표"),
    ("별도 재무상태표", "재무상태표"),
    ("손익 및 포괄손익계산서", "손익 및 포괄손익계산서"),
    ("연결포괄손익계산서", "포괄손익계산서"),
    ("요약재무상태표", None),
    ("1. 재무상태표", None),
    ("재무상태표 주석", None),
)

STATEMENT_TITLE_IN_ROWS_CASES: Final[
    tuple[tuple[tuple[tuple[str, ...], ...], str | None], ...]
] = (
    ((("연 결 포 괄 손 익 계 산 서", "제 5 기"),), "손익계산서"),
    ((("재 무 상 태 표",),), "재무상태표"),
    ((("주식회사 예시",), ("제 5 기",), ("현 금 흐 름 표",)), "현금흐름표"),
    (
        (("주식회사 예시",), ("제 5 기",), ("과 목",), ("현 금 흐 름 표",)),
        None,
    ),
    ((("자 본 변 동 표",),), "자본변동표"),
    ((("영업활동현금흐름", "100"),), None),
)

CLASSIFY_CASES: Final[tuple[tuple[str, SectionKind], ...]] = (
    ("재무상태표", SectionKind.BALANCE_SHEET),
    ("연결 포괄손익계산서", SectionKind.INCOME),
    ("손익계산서", SectionKind.INCOME),
    ("자본변동표", SectionKind.EQUITY),
    ("현금흐름표", SectionKind.CASH_FLOW),
    ("주석 3", SectionKind.NOTE),
    ("독립된 감사인의 감사보고서", SectionKind.OPINION),
    ("(첨부)재 무 제 표", SectionKind.OTHER),
)

NORMALIZATION_CALLER_CASES: Final[tuple[tuple[str, str], ...]] = (
    (" ", ""),
    ("\t", "연결"),
    ("\u00a0", "별도"),
    ("\u3000", "연결"),
)

_STATEMENT_TITLE_ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("재 무 상 태 표", "자산총계"),
    ("포 괄 손 익 계 산 서", "매출액"),
    ("자 본 변 동 표", "자본총계"),
    ("현 금 흐 름 표", "현금성자산"),
)


def _statement_document_with_separator(separator: str) -> bytes:
    triples = "".join(
        (
            f"<p>{title}</p>"
            f"{separator}"
            "<table><tr><td>과 목</td><td>제58기말</td></tr>"
            f"<tr><td>{row_label}</td><td>100</td></tr></table>"
        )
        for title, row_label in _STATEMENT_TITLE_ROWS
    )
    return f"<document><heading>(첨부)재 무 제 표</heading>{triples}</document>".encode()


@pytest.mark.parametrize(("text", "expected"), COMPACT_CASES)
def test_compact_removes_all_whitespace(text: str, expected: str) -> None:
    # Given
    source_text = text

    # When
    actual = compact(source_text)

    # Then
    assert actual == expected


@pytest.mark.parametrize(("line", "expected"), STATEMENT_TITLE_OF_LINE_CASES)
def test_statement_title_of_line_returns_exact_statement_title(
    line: str,
    expected: str | None,
) -> None:
    # Given
    source_line = line

    # When
    actual = statement_title_of_line(source_line)

    # Then
    assert actual == expected


@pytest.mark.parametrize(("rows", "expected"), STATEMENT_TITLE_IN_ROWS_CASES)
def test_statement_title_in_rows_reads_only_statement_header_rows(
    rows: tuple[tuple[str, ...], ...],
    expected: str | None,
) -> None:
    # Given
    source_rows = rows

    # When
    actual = statement_title_in_rows(source_rows)

    # Then
    assert actual == expected


@pytest.mark.parametrize(("title", "expected"), CLASSIFY_CASES)
def test_classify_maps_statement_title_to_section_kind(
    title: str,
    expected: SectionKind,
) -> None:
    # Given
    source_title = title

    # When
    actual = classify(source_title)

    # Then
    assert actual is expected


def test_all_production_callers_share_statement_title_normalization() -> None:
    for separator, scope in NORMALIZATION_CALLER_CASES:
        source_title = separator.join(f"{scope}재무상태표")
        expected_compact = f"{scope}재무상태표"
        rows = ((source_title,),)
        ordered = (
            DocumentBlock(kind=BlockKind.PARAGRAPH, text=source_title),
            DocumentBlock(kind=BlockKind.TABLE, rows=(("과 목", "100"),)),
        )
        report_title = separator.join("감사보고서")
        statement_set_title = separator.join(f"{scope}재무제표")
        xml = (
            f"<ROOT><TITLE>{report_title}</TITLE>"
            f"<TITLE>{statement_set_title}</TITLE></ROOT>"
        ).encode()
        expected_report_title = f"{scope or '별도'}감사보고서"

        actual = (
            compact(source_title),
            statement_title_of_line(source_title),
            statement_title_in_rows(rows),
            classify(source_title),
            document_model.classify_section(source_title),
            document_model._title_from_rows(rows),
            document_model._infer_section_title(ordered[0], ordered, 1),
            document_model._announces_table(ordered, 1),
            attachments._xml_report_title(xml),
        )

        assert actual == (
            expected_compact,
            "재무상태표",
            "재무상태표",
            SectionKind.BALANCE_SHEET,
            SectionKind.BALANCE_SHEET,
            "재무상태표",
            "재무상태표",
            True,
            expected_report_title,
        )


@pytest.mark.parametrize(
    ("separator", "expected_missing"),
    [
        pytest.param("", (), id="00_nothing"),
        pytest.param("<p></p>", (), id="01_blank_paragraph"),
        pytest.param("<p><br/></p>", (), id="02_br_only_paragraph"),
        pytest.param(
            f"<p>{chr(0x00A0)}</p>",
            (),
            id="03_nbsp_only_paragraph",
        ),
        pytest.param(
            f"<p>{chr(0x3000)}</p>",
            (),
            id="04_ideographic_space_only",
        ),
        pytest.param(
            "<p>제 58 기 2025년 12월 31일 현재</p>",
            (),
            id="05_period_line",
        ),
        pytest.param(
            "<p>현대자동차주식회사</p>",
            (),
            id="06_company_line",
        ),
        pytest.param(
            "<p>(단위: 백만원)</p>",
            (),
            id="07_unit_line",
        ),
        pytest.param(
            "<p>제 58 기 2025년 12월 31일 현재</p><p>(단위: 백만원)</p>",
            (),
            id="08_period_and_unit",
        ),
        # Deliberately out of scope: skipping headings is out of scope because
        # a heading opens a section on its own.
        pytest.param(
            "<heading>제 58 기</heading>",
            ("재무상태표", "손익·포괄손익", "자본변동표", "현금흐름표"),
            id="09_heading_between",
        ),
        pytest.param(
            "<img src='logo.jpg'/>",
            (),
            id="10_image_between",
        ),
        pytest.param(
            "<table><tr><td>제 58 기 2025년 12월 31일 현재</td></tr></table>",
            (),
            id="11_period_line_as_table",
        ),
        pytest.param(
            "<p></p><p>(단위: 백만원)</p>",
            (),
            id="12_blank_then_unit",
        ),
    ],
)
def test_statement_title_survives_realistic_separators(
    separator: str,
    expected_missing: tuple[str, ...],
) -> None:
    result = parse_html_document(_statement_document_with_separator(separator))

    assert result.ok is True
    assert result.data is not None
    assert excel_export._missing_core_sections(result.data) == expected_missing


def test_image_does_not_bridge_explanatory_paragraphs_to_unrelated_table() -> None:
    # Given
    html = (
        "<document>"
        "<heading>(첨부)재 무 제 표</heading>"
        "<p>재 무 상 태 표</p>"
        "<img src='statement.jpg'/>"
        "<p>위 본문은 이미지로 제공됩니다.</p>"
        "<p>아래 표는 참고 자료입니다.</p>"
        "<p>다음 내용은 감사 절차 설명입니다.</p>"
        "<table><tr><td>감사 절차</td><td>수행 결과</td></tr></table>"
        "</document>"
    ).encode()

    # When
    result = parse_html_document(html)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert "재무상태표" in excel_export._missing_core_sections(result.data)
