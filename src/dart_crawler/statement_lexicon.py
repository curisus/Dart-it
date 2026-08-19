"""Statement title vocabulary shared by document section inference."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Final


@unique
class SectionKind(StrEnum):
    """Workbook categories inferred from section titles."""

    OPINION = "opinion"
    BALANCE_SHEET = "balance_sheet"
    INCOME = "income"
    EQUITY = "equity"
    CASH_FLOW = "cash_flow"
    NOTE = "note"
    OTHER = "other"


statement_kinds: Final[frozenset[SectionKind]] = frozenset(
    {
        SectionKind.BALANCE_SHEET,
        SectionKind.INCOME,
        SectionKind.EQUITY,
        SectionKind.CASH_FLOW,
    }
)

_STATEMENT_TITLES: Final = (
    "재무상태표",
    "손익 및 포괄손익계산서",
    "손익계산서",
    "포괄손익계산서",
    "자본변동표",
    "현금흐름표",
)

_TITLE_SCOPES: Final = ("", "연결", "별도")


def compact(text: str) -> str:
    """Return text with every Unicode whitespace separator removed."""
    return "".join(text.split())


_TITLE_LINES: Final = {
    compact(f"{scope}{title}"): title
    for title in _STATEMENT_TITLES
    for scope in _TITLE_SCOPES
}

_TABLE_TERMS: Final = (
    ("재무상태표", "재무상태표"),
    # The income term deliberately catches/shadows compact comprehensive-income titles.
    ("손익계산서", "손익계산서"),
    ("자본변동표", "자본변동표"),
    ("현금흐름표", "현금흐름표"),
)


def statement_title_of_line(text: str) -> str | None:
    """Return an exact standalone statement title for a compacted line."""
    return _TITLE_LINES.get(compact(text))


def statement_title_in_rows(rows: tuple[tuple[str, ...], ...]) -> str | None:
    """Return a statement title found in the first three table header rows."""
    for row in rows[:3]:
        text = compact(" ".join(row))
        for needle, title in _TABLE_TERMS:
            if needle in text:
                return title
    return None


def classify(title: str) -> SectionKind:
    """Classify a section by stable DART report terminology."""
    compact_title = compact(title)
    if "재무상태표" in compact_title:
        return SectionKind.BALANCE_SHEET
    if "손익" in compact_title or "포괄손익" in compact_title:
        return SectionKind.INCOME
    if "자본변동" in compact_title:
        return SectionKind.EQUITY
    if "현금흐름" in compact_title:
        return SectionKind.CASH_FLOW
    if "주석" in compact_title:
        return SectionKind.NOTE
    if (
        "감사의견" in compact_title
        or "검토의견" in compact_title
        or "감사보고서" in compact_title
    ):
        return SectionKind.OPINION
    return SectionKind.OTHER
