"""Compare normalized statement amounts with official OpenDART account rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Final

from dart_crawler.api_models import FinancialAccount
from dart_crawler.document_model import BlockKind, ParsedDocument, SectionKind
from dart_crawler.result import JsonObject, WarningCode, WarningInfo
from dart_crawler.statement_lexicon import compact
from dart_crawler.value_parser import parse_cell_value

# Filings state amounts in won, thousands, millions, or hundred millions while
# OpenDART answers in won, so a row reconciles when any of these scales fits.
AMOUNT_SCALE_FACTORS: Final[tuple[int, ...]] = (1, 1_000, 1_000_000, 100_000_000)

# OpenDART tags every official row with the statement it belongs to. One account
# name means different amounts in different statements — 자본총계 is a balance
# sheet total and also an equity-statement column — so a source row is only ever
# compared with the official rows of its own statement.
#
# 자본변동표 (SCE) is deliberately absent. Its source layout is a matrix of
# equity components across columns while OpenDART returns one row per
# (component, event) pair, and nothing in the parsed table identifies which
# column is which component. Any cell-wise comparison there is guesswork, so the
# statement is left uncompared rather than warned about on every row.
_STATEMENT_DIVISIONS: Final[dict[SectionKind, frozenset[str]]] = {
    SectionKind.BALANCE_SHEET: frozenset({"BS"}),
    SectionKind.INCOME: frozenset({"IS", "CIS"}),
    SectionKind.CASH_FLOW: frozenset({"CF"}),
}

type OfficialIndex = Mapping[tuple[SectionKind, str], tuple[FinancialAccount, ...]]


def compare_statement_amounts(
    document: ParsedDocument,
    accounts: tuple[FinancialAccount, ...],
) -> tuple[WarningInfo, ...]:
    """Return warnings for missing, unlinked, or mismatched official values."""
    if not accounts:
        return (
            WarningInfo(
                code=WarningCode.COMPARISON_UNAVAILABLE,
                message="공식 전체 계정과목 자료가 없어 금액을 비교하지 못했습니다.",
            ),
        )
    official = official_index(accounts)
    warnings: list[WarningInfo] = []
    for section in document.sections:
        if section.kind not in _STATEMENT_DIVISIONS:
            continue
        for block in section.blocks:
            if block.kind is not BlockKind.TABLE:
                continue
            for row in block.rows:
                warning = _row_warning(row, section.kind, official)
                if warning is not None:
                    warnings.append(warning)
    return tuple(warnings)


def official_index(
    accounts: tuple[FinancialAccount, ...],
) -> dict[tuple[SectionKind, str], tuple[FinancialAccount, ...]]:
    """Group official rows by the statement and account name they carry.

    A name is not unique even inside one statement: a balance sheet lists the
    current and non-current halves of 기타금융자산 under the same label. Every
    row with the name is kept so a source amount can reconcile with any of them
    instead of with whichever one happened to be indexed last.
    """
    grouped: dict[tuple[SectionKind, str], list[FinancialAccount]] = defaultdict(list)
    for account in accounts:
        name = compact(account.account_nm)
        if not name:
            continue
        for kind, divisions in _STATEMENT_DIVISIONS.items():
            if account.sj_div in divisions:
                grouped[kind, name].append(account)
    return {key: tuple(values) for key, values in grouped.items()}


def _row_warning(
    row: tuple[str, ...],
    kind: SectionKind,
    official: OfficialIndex,
) -> WarningInfo | None:
    if len(row) < 2:
        return None
    account_name = compact(row[0])
    if not account_name:
        return None
    candidates = official.get((kind, account_name))
    if not candidates:
        return None
    # Statement rows put a note-reference number, the current term, and prior
    # terms to the right of the account name in an order that varies by filer,
    # so every cell is a candidate rather than only the first one.
    cells = row[1:]
    source_values = [value for value in map(_numeric, cells) if value is not None]
    official_values = [
        value
        for value in (_numeric(account.thstrm_amount) for account in candidates)
        if value is not None
    ]
    if not official_values or not source_values:
        return WarningInfo(
            code=WarningCode.COMPARISON_UNAVAILABLE,
            message="계정의 숫자 연결을 확인하지 못했습니다.",
            details={"account_name": account_name},
        )
    if _reconciles(source_values, official_values):
        return None
    details: JsonObject = {
        "account_name": account_name,
        "statement": kind.value,
        "source_values": list(cells),
        "official_values": [account.thstrm_amount for account in candidates],
        "unit_scales": list(AMOUNT_SCALE_FACTORS),
    }
    return WarningInfo(
        code=WarningCode.AMOUNT_MISMATCH,
        message="원문 금액이 어떤 단위 배율로도 OpenDART 금액과 일치하지 않습니다.",
        details=details,
    )


def matching_unit_scale(source_value: Decimal, official_value: Decimal) -> int | None:
    """Return the unit scale that reconciles one source amount, or None.

    Sources bracket expense and deduction lines that OpenDART reports without a
    sign, so magnitudes are compared and the sign convention is not a defect.
    This is the single definition of "these two amounts agree", shared with the
    live validation script so the two never drift apart.
    """
    magnitude = abs(official_value)
    for scale in AMOUNT_SCALE_FACTORS:
        if abs(source_value) * scale == magnitude:
            return scale
    return None


def _reconciles(
    source_values: list[Decimal],
    official_values: list[Decimal],
) -> bool:
    return any(
        matching_unit_scale(source_value, official_value) is not None
        for source_value in source_values
        for official_value in official_values
    )


def _numeric(value: str) -> Decimal | None:
    parsed = parse_cell_value(value)
    if not isinstance(parsed, (int, float)) or isinstance(parsed, bool):
        return None
    try:
        return Decimal(str(parsed))
    except InvalidOperation:
        return None
