"""Safe conversion of table text into numeric or forced-string cell values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"^\(?[+-]?\d+(?:\.\d+)?\)?$")
_NEGATIVE_FORMULA = re.compile(
    r"^-[ \t]*(?:[A-Za-z_$][A-Za-z0-9_.$]*\s*\(|\$?[A-Z]{1,3}\$?\d+)"
)
_LEADING_INDENT = re.compile(r"^[ \t\u00a0\u3000]+")


def parse_cell_value(text: str, *, unit_multiplier: int = 1) -> int | float | str:
    """Parse clear amounts while keeping indented external text as text."""
    normalized = text.strip()
    if not normalized:
        return ""
    if _NUMBER.fullmatch(normalized.replace(",", "")):
        negative = normalized.startswith("(") and normalized.endswith(")")
        number_text = normalized.strip("()").replace(",", "")
        try:
            number = Decimal(number_text) * unit_multiplier
        except InvalidOperation:
            return _safe_text(normalized)
        if negative:
            number = -number
        if number == number.to_integral_value():
            return int(number)
        return float(number)
    indent = _LEADING_INDENT.match(text)
    if indent is not None:
        return indent.group() + normalized
    return _safe_text(normalized)


def _safe_text(value: str) -> str:
    if value.startswith(("=", "+", "@")) or _NEGATIVE_FORMULA.match(value):
        return "'" + value
    return value
