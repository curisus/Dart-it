"""Place HTML/XML table cells on one rectangular grid."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableCell:
    """One source cell with its declared horizontal and vertical spans."""

    text: str
    colspan: int = 1
    rowspan: int = 1


type CellGrid = tuple[tuple[str, ...], ...]
type MergeRange = tuple[int, int, int, int]


def layout_table(
    source_rows: Sequence[Sequence[TableCell]],
) -> tuple[CellGrid, tuple[MergeRange, ...]]:
    """Expand row and column spans into rows and merge coordinates."""
    values: list[list[str]] = []
    occupied: set[tuple[int, int]] = set()
    merged_ranges: list[MergeRange] = []
    for source_row_number, source_cells in enumerate(source_rows, start=1):
        _ensure_rows(values, source_row_number)
        column_number = 1
        for cell in source_cells:
            colspan = max(1, cell.colspan)
            rowspan = max(1, cell.rowspan)
            while (source_row_number, column_number) in occupied:
                column_number += 1
            end_row = source_row_number + rowspan - 1
            end_column = column_number + colspan - 1
            _ensure_rows(values, end_row)
            for row_number in range(source_row_number, end_row + 1):
                _ensure_columns(values[row_number - 1], end_column)
                for current_column in range(column_number, end_column + 1):
                    occupied.add((row_number, current_column))
                    if (
                        row_number == source_row_number
                        and current_column == column_number
                    ):
                        values[row_number - 1][current_column - 1] = cell.text
            if colspan > 1 or rowspan > 1:
                merged_ranges.append(
                    (source_row_number, column_number, end_row, end_column)
                )
            column_number = end_column + 1
    width = max((len(row) for row in values), default=0)
    rows = tuple(
        tuple(row + [""] * (width - len(row)))
        for row in values
    )
    return rows, tuple(merged_ranges)

def _ensure_rows(values: list[list[str]], row_number: int) -> None:
    while len(values) < row_number:
        values.append([])


def _ensure_columns(row: list[str], column_number: int) -> None:
    row.extend("" for _ in range(column_number - len(row)))
