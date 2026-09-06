"""Read OpenDART amount columns as numbers instead of as text.

OpenDART returns every field as a string, amounts included, so a spreadsheet
built from a query answers with text in the amount columns and neither SUM nor
sorting works on them.

The columns that become numbers are named explicitly rather than detected from
their values. Identifiers are digit strings too — ``corp_code`` is "00126380"
and ``rcept_no`` is "20260310002820" — and reading those as numbers drops the
leading zeros of the first and prints the second as 20,260,310,002,820. A name
missing from the list keeps today's behaviour and loses nothing; a name wrongly
included destroys data, so the list is an allowlist.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

from dart_crawler.excel_page_models import ExcelRow, ExcelScalar
from dart_crawler.value_parser import parse_number

# Amount and ratio fields of the three financial models in api_models.py.
# Ordinals (``ord``), dates (``thstrm_dt``), and codes are deliberately absent.
AMOUNT_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "thstrm_amount",
        "thstrm_add_amount",
        "frmtrm_amount",
        "frmtrm_q_amount",
        "frmtrm_add_amount",
        "bfefrmtrm_amount",
        "idx_val",
    }
)

# Six decimal places is past any ratio OpenDART publishes; the cap stops one
# stray value from widening every cell in its column.
_MAX_DISPLAYED_DECIMALS: Final = 6
_RENAMED_SOURCE = re.compile(r"^source_(?P<name>.+?)(?:_\d+)?$")


def amount_field_name(column: str) -> str:
    """Return the source field a column carries, undoing collision renaming."""
    match = _RENAMED_SOURCE.match(column)
    return column if match is None else match.group("name")


def coerce_numeric_columns(
    columns: tuple[str, ...],
    rows: tuple[ExcelRow, ...],
) -> tuple[tuple[ExcelRow, ...], tuple[str, ...]]:
    """Return the rows with every amount column read as a number.

    A column qualifies when it is named as an amount, holds only text, and
    every non-blank value of it reads as a number. Blank values neither
    disqualify the column nor become numbers, so an absent amount stays absent
    instead of turning into a zero.
    """
    numeric = tuple(
        column for column in columns if _is_numeric_column(column, rows)
    )
    if not numeric:
        return rows, ()
    coerced = frozenset(numeric)
    converted = tuple(
        {
            column: _as_number(value) if column in coerced else value
            for column, value in row.items()
        }
        for row in rows
    )
    return converted, numeric


def numeric_column_formats(
    numeric_columns: tuple[str, ...],
    rows: tuple[ExcelRow, ...],
) -> dict[str, str]:
    """Return the display format each coerced column is written with."""
    formats: dict[str, str] = {}
    for column in numeric_columns:
        decimals = max(
            (
                _decimal_places(value)
                for row in rows
                if isinstance(value := row.get(column), float)
            ),
            default=0,
        )
        formats[column] = (
            "#,##0" if decimals == 0 else "#,##0." + "0" * decimals
        )
    return formats


def _is_numeric_column(column: str, rows: tuple[ExcelRow, ...]) -> bool:
    if amount_field_name(column) not in AMOUNT_FIELD_NAMES:
        return False
    seen_number = False
    for row in rows:
        value = row.get(column)
        if not isinstance(value, str):
            return False
        if not value.strip():
            continue
        if parse_number(value) is None:
            return False
        seen_number = True
    return seen_number


def _as_number(value: ExcelScalar) -> ExcelScalar:
    if not isinstance(value, str) or not value.strip():
        return value
    number = parse_number(value)
    return value if number is None else number


def _decimal_places(value: float) -> int:
    exponent = Decimal(str(value)).as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= 0:
        return 0
    return min(-exponent, _MAX_DISPLAYED_DECIMALS)
