from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from openpyxl.compat import safe_string

from dart_crawler.excel_page_models import ExcelScalar

_MAX_EXACT_INTEGER = 2**53
_ILLEGAL_XML_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True, slots=True)
class ProjectedExcelCell:
    value: ExcelScalar


@dataclass(frozen=True, slots=True)
class ExcelProjectionFailure:
    reason: Literal["excel_cell_projection_failed"]


type ExcelProjection = ProjectedExcelCell | ExcelProjectionFailure


def project_excel_cell(value: ExcelScalar) -> ExcelProjection:
    if isinstance(value, bool):
        return ProjectedExcelCell(value)
    if isinstance(value, int):
        return _project_integer(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ExcelProjectionFailure("excel_cell_projection_failed")
        return ProjectedExcelCell(value)
    if isinstance(value, str):
        retained = value[:32767]
        if _ILLEGAL_XML_CONTROL.search(retained) is not None:
            return ExcelProjectionFailure("excel_cell_projection_failed")
        return ProjectedExcelCell(retained)
    return ProjectedExcelCell(None)


def _project_integer(integer: int) -> ExcelProjection:
    if abs(integer) <= _MAX_EXACT_INTEGER:
        return ProjectedExcelCell(integer)
    try:
        number = float(integer)
    except OverflowError:
        return ExcelProjectionFailure("excel_cell_projection_failed")
    if not math.isfinite(number):
        return ExcelProjectionFailure("excel_cell_projection_failed")
    return ProjectedExcelCell(number)


def reopened_values_match(
    expected: ExcelScalar,
    actual: ExcelScalar,
) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, int):
        return (
            isinstance(actual, int)
            and not isinstance(actual, bool)
            and actual == expected
        )
    if isinstance(expected, float):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        if not expected and not actual:
            return True
        return safe_string(expected) == safe_string(actual)
    if isinstance(expected, str):
        return actual == expected or (expected == "" and actual is None)
    return actual is None
