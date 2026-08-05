"""Safe conversion of table text into numeric or forced-string cell values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"^\(?[+-]?\d+(?:\.\d+)?\)?$")


def parse_cell_value(text: str, *, unit_multiplier: int = 1) -> int | float | str:
    """Parse clear amounts while keeping ambiguous external text as text."""
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
    return _safe_text(normalized)


def _safe_text(value: str) -> str:
    if value[0] in "=+-@":
        return "'" + value
    return value
