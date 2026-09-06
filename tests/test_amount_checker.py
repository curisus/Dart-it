from dart_crawler.amount_checker import compare_statement_amounts
from dart_crawler.api_models import FinancialAccount
from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
)


def _rows_document(
    *rows: tuple[str, ...],
    kind: SectionKind = SectionKind.BALANCE_SHEET,
    title: str = "재무상태표",
) -> ParsedDocument:
    return ParsedDocument(
        sections=(
            DocumentSection(
                title=title,
                kind=kind,
                blocks=(DocumentBlock(BlockKind.TABLE, rows=rows),),
            ),
        ),
        source_sha256="a" * 64,
        source_type="xml",
    )


def _document(value: str) -> ParsedDocument:
    return _rows_document(("자산", value))


def _account(
    value: str,
    account_nm: str = "자산",
    sj_div: str = "BS",
) -> FinancialAccount:
    return FinancialAccount(
        fs_div="OFS",
        sj_div=sj_div,
        bsns_year="2025",
        reprt_code="11011",
        account_id="ifrs-full_Assets",
        account_nm=account_nm,
        thstrm_amount=value,
        thstrm_add_amount="",
        frmtrm_amount="",
        frmtrm_q_amount="",
        frmtrm_add_amount="",
        currency="KRW",
    )


def test_amount_checker_reports_mismatch_without_changing_source_document() -> None:
    document = _document("100")

    warnings = compare_statement_amounts(document, (_account("90"),))

    assert warnings[0].code.value == "AMOUNT_MISMATCH"
    assert document.sections[0].blocks[0].rows[0][1] == "100"


def test_amount_checker_reports_unavailable_comparison() -> None:
    warnings = compare_statement_amounts(_document("100"), ())

    assert warnings[0].code.value == "COMPARISON_UNAVAILABLE"


def test_amount_checker_matches_indented_account_names() -> None:
    document = _rows_document(("   자산", "100"))

    warnings = compare_statement_amounts(document, (_account("90"),))

    assert [warning.code.value for warning in warnings] == ["AMOUNT_MISMATCH"]
    assert warnings[0].details["account_name"] == "자산"


def test_amount_checker_matches_account_names_containing_inner_spaces() -> None:
    """Filings space out totals as "자 본 총 계" while OpenDART does not."""
    document = _rows_document(("자 산", "100"))

    warnings = compare_statement_amounts(document, (_account("90"),))

    assert [warning.code.value for warning in warnings] == ["AMOUNT_MISMATCH"]
    assert warnings[0].details["account_name"] == "자산"


def test_amount_checker_reconciles_past_a_note_reference_column() -> None:
    """The amount does not sit in a fixed column: a note number may precede it."""
    document = _rows_document(("재고자산", "8", "10,396,303"))

    warnings = compare_statement_amounts(
        document,
        (_account("10396303000000", account_nm="재고자산"),),
    )

    assert warnings == ()


def test_amount_checker_accepts_every_unit_a_filing_may_state() -> None:
    for source, official in (
        ("10,396,303", "10396303"),
        ("10,396,303", "10396303000"),
        ("10,396,303", "10396303000000"),
        ("10,396,303", "1039630300000000"),
    ):
        warnings = compare_statement_amounts(
            _rows_document(("재고자산", source)),
            (_account(official, account_nm="재고자산"),),
        )

        assert warnings == (), (source, official)


def test_amount_checker_accepts_parenthesized_negatives_of_unsigned_official() -> None:
    """Sources bracket expense lines that OpenDART reports without a sign."""
    document = _rows_document(
        ("보험금비용", "(14,578,519)"),
        kind=SectionKind.INCOME,
        title="포괄손익계산서",
    )

    warnings = compare_statement_amounts(
        document,
        (_account("14578519000000", account_nm="보험금비용", sj_div="CIS"),),
    )

    assert warnings == ()


def test_amount_checker_accepts_any_official_row_sharing_one_name() -> None:
    """A balance sheet labels its current and non-current halves identically."""
    document = _rows_document(("기타금융자산", "4,5,6,20", "195,196"))

    warnings = compare_statement_amounts(
        document,
        (
            _account("195196000000", account_nm="기타금융자산"),
            _account("1100011000000", account_nm="기타금융자산"),
        ),
    )

    assert warnings == ()


def test_amount_checker_compares_within_the_statement_the_row_belongs_to() -> None:
    """자본총계 is a balance-sheet total and an equity-statement column alike."""
    accounts = (
        _account("117318562000000", account_nm="자본총계", sj_div="BS"),
        _account("8778664000000", account_nm="자본총계", sj_div="SCE"),
    )

    reconciled = compare_statement_amounts(
        _rows_document(("자 본 총 계", "", "117,318,562")),
        accounts,
    )
    borrowed = compare_statement_amounts(
        _rows_document(("자 본 총 계", "", "8,778,664")),
        accounts,
    )

    assert reconciled == ()
    assert [warning.code.value for warning in borrowed] == ["AMOUNT_MISMATCH"]


def test_amount_checker_leaves_the_equity_statement_uncompared() -> None:
    """Its columns are equity components the parsed table cannot identify."""
    document = _rows_document(
        ("당기순이익", "-", "-", "5,078,221", "(49,615)", "5,028,606"),
        kind=SectionKind.EQUITY,
        title="자본변동표",
    )

    warnings = compare_statement_amounts(
        document,
        (_account("0", account_nm="당기순이익", sj_div="SCE"),),
    )

    assert warnings == ()


def test_amount_checker_still_reports_a_row_no_scale_can_reconcile() -> None:
    document = _rows_document(("자산총계", "9", "999,999"))

    warnings = compare_statement_amounts(
        document,
        (_account("123456789000000", account_nm="자산총계"),),
    )

    assert [warning.code.value for warning in warnings] == ["AMOUNT_MISMATCH"]
    details = warnings[0].details
    assert details["source_values"] == ["9", "999,999"]
    assert details["official_values"] == ["123456789000000"]
    assert details["statement"] == "balance_sheet"


def test_amount_checker_reports_unavailable_when_no_cell_is_numeric() -> None:
    document = _rows_document(("자산", "주석", "당기"))

    warnings = compare_statement_amounts(document, (_account("100"),))

    assert [warning.code.value for warning in warnings] == ["COMPARISON_UNAVAILABLE"]
