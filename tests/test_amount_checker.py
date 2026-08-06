from dart_crawler.amount_checker import compare_statement_amounts
from dart_crawler.api_models import FinancialAccount
from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
)


def _document(value: str) -> ParsedDocument:
    return ParsedDocument(
        sections=(
            DocumentSection(
                title="재무상태표",
                kind=SectionKind.BALANCE_SHEET,
                blocks=(DocumentBlock(BlockKind.TABLE, rows=(("자산", value),)),),
            ),
        ),
        source_sha256="a" * 64,
        source_type="xml",
    )


def _account(value: str) -> FinancialAccount:
    return FinancialAccount(
        fs_div="OFS",
        sj_div="BS",
        bsns_year="2025",
        reprt_code="11011",
        account_id="ifrs-full_Assets",
        account_nm="자산",
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
    document = ParsedDocument(
        sections=(
            DocumentSection(
                title="재무상태표",
                kind=SectionKind.BALANCE_SHEET,
                blocks=(DocumentBlock(BlockKind.TABLE, rows=(("   자산", "100"),)),),
            ),
        ),
        source_sha256="a" * 64,
        source_type="xml",
    )

    warnings = compare_statement_amounts(document, (_account("90"),))

    assert [warning.code.value for warning in warnings] == ["AMOUNT_MISMATCH"]
    assert warnings[0].details["account_name"] == "자산"
