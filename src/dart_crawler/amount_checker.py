"""Compare normalized statement amounts with official OpenDART account rows."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from dart_crawler.api_models import FinancialAccount
from dart_crawler.document_model import BlockKind, ParsedDocument, SectionKind
from dart_crawler.result import WarningCode, WarningInfo
from dart_crawler.value_parser import parse_cell_value


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
    official = {account.account_nm: account for account in accounts}
    warnings: list[WarningInfo] = []
    for section in document.sections:
        if section.kind not in {
            SectionKind.BALANCE_SHEET,
            SectionKind.INCOME,
            SectionKind.EQUITY,
            SectionKind.CASH_FLOW,
        }:
            continue
        for block in section.blocks:
            if block.kind is not BlockKind.TABLE:
                continue
            for row in block.rows:
                if len(row) < 2 or row[0] not in official:
                    continue
                source_value = _numeric(row[1])
                official_value = _numeric(official[row[0]].thstrm_amount)
                if source_value is None or official_value is None:
                    warnings.append(
                        WarningInfo(
                            code=WarningCode.COMPARISON_UNAVAILABLE,
                            message="계정의 숫자 연결을 확인하지 못했습니다.",
                            details={"account_name": row[0]},
                        )
                    )
                    continue
                if source_value != official_value:
                    warnings.append(
                        WarningInfo(
                            code=WarningCode.AMOUNT_MISMATCH,
                            message="원문 금액과 OpenDART 비교 금액이 다릅니다.",
                            details={
                                "account_name": row[0],
                                "source_value": row[1],
                                "official_value": official[row[0]].thstrm_amount,
                            },
                        )
                    )
    return tuple(warnings)


def _numeric(value: str) -> Decimal | None:
    parsed = parse_cell_value(value)
    if not isinstance(parsed, (int, float)) or isinstance(parsed, bool):
        return None
    try:
        return Decimal(str(parsed))
    except InvalidOperation:
        return None
