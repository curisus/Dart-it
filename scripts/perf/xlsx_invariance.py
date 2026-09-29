"""Result-data invariance: compare two xlsx workbooks or two row datasets.

A workbook is reduced to a canonical dump - sheet names in order, each
sheet's visibility state and freeze panes, every non-empty cell (coordinate,
typed value, number format, horizontal/vertical alignment, wrap text, bold),
merged ranges and column widths - after removing the allow-listed cells that
legitimately change on every run. Two workbooks are identical when their dumps
are equal, and ``values_sha256`` is the SHA-256 of that dump, so a flow record
can carry one hash instead of the file. ``flow_identity`` adds a flow's
warning codes to that hash (or to a remote flow's rows hash): the identity two
runs of a flow must share.

This module is imported by the unit tests, so it depends on openpyxl and the
standard library only (never on the fitness runner or anything networked).

Usage:
  uv run python scripts/perf/xlsx_invariance.py <a.xlsx> <b.xlsx>
Exit 0 when identical, 1 when they differ, 2 when a file cannot be read.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import openpyxl
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.worksheet.worksheet import Worksheet

type CellDump = tuple[str, str, str, str, str, bool, bool]
"""(value type tag, value text, number format, horizontal alignment, vertical
alignment, wrap text, bold) of one non-empty cell."""

type JsonScalar = str | int | float | bool | None

MAX_REPORTED_DIFFERENCES: Final = 200


@dataclass(frozen=True, slots=True)
class AllowListedCell:
    """A key/value row whose value cell is excluded from the comparison."""

    sheet: str
    key: str
    key_column: int = 1
    value_column: int = 2


# Only fields that change on every run by construction belong here; anything
# derived from the source document or the request must stay compared.
#
# - Report export (export_report_excel, sheet "수집정보", written by
#   workbook_writer._metadata / workbook_metadata.shared_metadata_expectations):
#   every field is derived from the source attachment, the parser and the
#   validation counts (rcept_no, source_sha256, parser_version, section and
#   warning lists, coverage counts). It records no clock time, elapsed time or
#   output path, so nothing on it is allow-listed.
# - Query export (export_query_excel, sheet "metadata", written by
#   excel_query_workbook_plan.metadata_rows): the rows are schema_version,
#   domain, argument.*, request_fingerprint, source_fingerprint, dataset_id,
#   total_rows, generated_at_utc, provenance and data_sheet_names. Only
#   generated_at_utc varies: it is SystemExcelClock.now_utc() formatted as
#   "%Y-%m-%dT%H:%M:%S.%fZ" at plan time. Its text length is fixed, so the
#   column width derived from it cannot vary either.
DEFAULT_ALLOW_LIST: Final[tuple[AllowListedCell, ...]] = (
    AllowListedCell(sheet="metadata", key="generated_at_utc"),
)


@dataclass(frozen=True, slots=True)
class SheetDump:
    name: str
    cells: Mapping[str, CellDump]
    merged: tuple[str, ...]
    column_widths: Mapping[str, tuple[int, int, float]]
    allow_listed: tuple[str, ...]
    freeze_panes: str
    sheet_state: str


@dataclass(frozen=True, slots=True)
class WorkbookDump:
    sheets: tuple[SheetDump, ...]

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return tuple(sheet.name for sheet in self.sheets)


@dataclass(frozen=True, slots=True)
class Difference:
    kind: str
    sheet: str
    location: str
    a: str
    b: str


@dataclass(frozen=True, slots=True)
class InvarianceReport:
    identical: bool
    difference_count: int
    differences: tuple[Difference, ...]
    a_sha256: str
    b_sha256: str
    summary: Mapping[str, int] = field(default_factory=dict)


def _typed_value(cell: Cell) -> tuple[str, str]:
    value: object = cell.value
    if cell.data_type == "f":
        return ("f", str(value))
    if isinstance(value, bool):
        return ("b", "true" if value else "false")
    if isinstance(value, int):
        return ("i", str(value))
    if isinstance(value, float):
        return ("r", repr(value))
    if isinstance(value, str):
        return ("s", value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return ("d", value.isoformat())
    return ("o", repr(value))


def _allow_listed_coordinates(
    sheet: Worksheet,
    allow_list: Sequence[AllowListedCell],
) -> set[str]:
    rules = [rule for rule in allow_list if rule.sheet == sheet.title]
    if not rules:
        return set()
    excluded: set[str] = set()
    for row in sheet.iter_rows():
        for rule in rules:
            if len(row) < max(rule.key_column, rule.value_column):
                continue
            if row[rule.key_column - 1].value == rule.key:
                excluded.add(row[rule.value_column - 1].coordinate)
    return excluded


def _sheet_cells(sheet: Worksheet, excluded: set[str]) -> dict[str, CellDump]:
    cells: dict[str, CellDump] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell, MergedCell) or cell.value is None:
                continue
            if cell.coordinate in excluded:
                continue
            tag, text = _typed_value(cell)
            alignment = cell.alignment
            cells[cell.coordinate] = (
                tag,
                text,
                str(cell.number_format),
                str(alignment.horizontal or ""),
                str(alignment.vertical or ""),
                bool(alignment.wrap_text),
                bool(cell.font.bold),
            )
    return cells


def _column_widths(sheet: Worksheet) -> dict[str, tuple[int, int, float]]:
    widths: dict[str, tuple[int, int, float]] = {}
    for letter, dimension in sheet.column_dimensions.items():
        width = dimension.width
        if width is None:
            continue
        widths[str(letter)] = (
            int(dimension.min or 0),
            int(dimension.max or 0),
            float(width),
        )
    return widths


def dump_sheet(
    sheet: Worksheet,
    allow_list: Sequence[AllowListedCell] = DEFAULT_ALLOW_LIST,
) -> SheetDump:
    excluded = _allow_listed_coordinates(sheet, allow_list)
    return SheetDump(
        name=sheet.title,
        cells=_sheet_cells(sheet, excluded),
        merged=tuple(sorted(str(merged) for merged in sheet.merged_cells.ranges)),
        column_widths=_column_widths(sheet),
        allow_listed=tuple(sorted(excluded)),
        freeze_panes=str(sheet.freeze_panes or ""),
        sheet_state=str(sheet.sheet_state),
    )


def dump_workbook(
    path: Path,
    allow_list: Sequence[AllowListedCell] = DEFAULT_ALLOW_LIST,
) -> WorkbookDump:
    workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        return WorkbookDump(
            sheets=tuple(dump_sheet(sheet, allow_list) for sheet in workbook.worksheets)
        )
    finally:
        workbook.close()


def _dump_json(dump: WorkbookDump) -> list[object]:
    return [
        {
            "name": sheet.name,
            "merged": list(sheet.merged),
            "column_widths": {
                letter: list(width)
                for letter, width in sorted(sheet.column_widths.items())
            },
            "allow_listed": list(sheet.allow_listed),
            "freeze_panes": sheet.freeze_panes,
            "sheet_state": sheet.sheet_state,
            "cells": [
                [coordinate, *cell] for coordinate, cell in sorted(sheet.cells.items())
            ],
        }
        for sheet in dump.sheets
    ]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def values_sha256(dump: WorkbookDump) -> str:
    return hashlib.sha256(canonical_json(_dump_json(dump)).encode("utf-8")).hexdigest()


def xlsx_sha256_of_values(path: Path) -> str:
    return values_sha256(dump_workbook(path))


def flow_identity(data_sha256: str | None, warning_codes: Iterable[str]) -> str | None:
    """SHA-256 of a flow's data hash plus its sorted unique warning codes.

    No warning code is allow-listed: none is known to vary between two runs of
    identical code (a code that did would need a documented exclusion here).
    """
    if not data_sha256:
        return None
    payload = {"data_sha256": data_sha256, "warning_codes": sorted(set(warning_codes))}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _cell_differences(a: SheetDump, b: SheetDump) -> Iterator[Difference]:
    for coordinate in sorted(set(a.cells) | set(b.cells)):
        a_cell = a.cells.get(coordinate)
        b_cell = b.cells.get(coordinate)
        if a_cell == b_cell:
            continue
        if a_cell is None or b_cell is None:
            yield Difference(
                "missing_cell", a.name, coordinate, repr(a_cell), repr(b_cell)
            )
        elif a_cell[:2] != b_cell[:2]:
            yield Difference(
                "cell_value", a.name, coordinate, repr(a_cell[:2]), repr(b_cell[:2])
            )
        else:
            yield from _cell_style_differences(a.name, coordinate, a_cell, b_cell)


def _cell_style_differences(
    sheet: str, coordinate: str, a: CellDump, b: CellDump
) -> Iterator[Difference]:
    if a[2] != b[2]:
        yield Difference("number_format", sheet, coordinate, a[2], b[2])
    if a[3:6] != b[3:6]:
        yield Difference("alignment", sheet, coordinate, repr(a[3:6]), repr(b[3:6]))
    if a[6] != b[6]:
        yield Difference("font_bold", sheet, coordinate, repr(a[6]), repr(b[6]))


def _sheet_differences(a: SheetDump, b: SheetDump) -> Iterator[Difference]:
    yield from _cell_differences(a, b)
    if a.merged != b.merged:
        only_a = sorted(set(a.merged) - set(b.merged))
        only_b = sorted(set(b.merged) - set(a.merged))
        yield Difference(
            "merged_ranges", a.name, "", ",".join(only_a), ",".join(only_b)
        )
    for letter in sorted(set(a.column_widths) | set(b.column_widths)):
        a_width = a.column_widths.get(letter)
        b_width = b.column_widths.get(letter)
        if a_width != b_width:
            yield Difference(
                "column_width", a.name, letter, repr(a_width), repr(b_width)
            )
    if a.freeze_panes != b.freeze_panes:
        yield Difference("freeze_panes", a.name, "", a.freeze_panes, b.freeze_panes)
    if a.sheet_state != b.sheet_state:
        yield Difference("sheet_state", a.name, "", a.sheet_state, b.sheet_state)
    if a.allow_listed != b.allow_listed:
        yield Difference(
            "allow_listed_cells",
            a.name,
            "",
            ",".join(a.allow_listed),
            ",".join(b.allow_listed),
        )


def _workbook_differences(a: WorkbookDump, b: WorkbookDump) -> Iterator[Difference]:
    if a.sheet_names != b.sheet_names:
        yield Difference(
            "sheet_names",
            "",
            "",
            json.dumps(a.sheet_names, ensure_ascii=False),
            json.dumps(b.sheet_names, ensure_ascii=False),
        )
    b_sheets = {sheet.name: sheet for sheet in b.sheets}
    for a_sheet in a.sheets:
        b_sheet = b_sheets.get(a_sheet.name)
        if b_sheet is not None:
            yield from _sheet_differences(a_sheet, b_sheet)


def compare_dumps(a: WorkbookDump, b: WorkbookDump) -> InvarianceReport:
    kept: list[Difference] = []
    summary: dict[str, int] = {}
    count = 0
    for difference in _workbook_differences(a, b):
        count += 1
        summary[difference.kind] = summary.get(difference.kind, 0) + 1
        if len(kept) < MAX_REPORTED_DIFFERENCES:
            kept.append(difference)
    return InvarianceReport(
        identical=count == 0,
        difference_count=count,
        differences=tuple(kept),
        a_sha256=values_sha256(a),
        b_sha256=values_sha256(b),
        summary=summary,
    )


def compare_workbooks(
    a_path: Path,
    b_path: Path,
    allow_list: Sequence[AllowListedCell] = DEFAULT_ALLOW_LIST,
) -> InvarianceReport:
    return compare_dumps(
        dump_workbook(a_path, allow_list), dump_workbook(b_path, allow_list)
    )


@dataclass(frozen=True, slots=True)
class RowDataset:
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, JsonScalar], ...]


def compare_row_datasets(a: RowDataset, b: RowDataset) -> InvarianceReport:
    """Compare two loaded row datasets (columns + rows) value by value."""
    differences: list[Difference] = []
    count = 0

    def note(difference: Difference) -> None:
        nonlocal count
        count += 1
        if len(differences) < MAX_REPORTED_DIFFERENCES:
            differences.append(difference)

    if a.columns != b.columns:
        note(
            Difference(
                "columns", "", "", canonical_json(a.columns), canonical_json(b.columns)
            )
        )
    if len(a.rows) != len(b.rows):
        note(Difference("row_count", "", "", str(len(a.rows)), str(len(b.rows))))
    for index, (a_row, b_row) in enumerate(zip(a.rows, b.rows, strict=False)):
        if canonical_json(a_row) != canonical_json(b_row):
            note(
                Difference(
                    "row", "", str(index), canonical_json(a_row), canonical_json(b_row)
                )
            )
    summary: dict[str, int] = {}
    for difference in differences:
        summary[difference.kind] = summary.get(difference.kind, 0) + 1
    return InvarianceReport(
        identical=count == 0,
        difference_count=count,
        differences=tuple(differences),
        a_sha256=rows_sha256(a),
        b_sha256=rows_sha256(b),
        summary=summary,
    )


def rows_sha256(dataset: RowDataset) -> str:
    payload = {
        "columns": list(dataset.columns),
        "rows": [dict(row) for row in dataset.rows],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def report_json(report: InvarianceReport) -> dict[str, object]:
    return {
        "identical": report.identical,
        "difference_count": report.difference_count,
        "summary": dict(report.summary),
        "a_sha256": report.a_sha256,
        "b_sha256": report.b_sha256,
        "differences": [
            {
                "kind": difference.kind,
                "sheet": difference.sheet,
                "location": difference.location,
                "a": difference.a,
                "b": difference.b,
            }
            for difference in report.differences
        ],
    }


def format_report(report: InvarianceReport, *, limit: int = 20) -> str:
    lines = [
        f"identical: {report.identical}",
        f"values_sha256 a: {report.a_sha256}",
        f"values_sha256 b: {report.b_sha256}",
        f"differences: {report.difference_count}",
    ]
    lines.extend(f"  {kind}: {count}" for kind, count in sorted(report.summary.items()))
    for difference in report.differences[:limit]:
        where = "!".join(
            part for part in (difference.sheet, difference.location) if part
        )
        lines.append(f"  [{difference.kind}] {where}: {difference.a} != {difference.b}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two xlsx files for value invariance"
    )
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    namespace = parser.parse_args(argv)
    a_path: Path = namespace.a
    b_path: Path = namespace.b
    for path in (a_path, b_path):
        if not path.is_file():
            print(f"not a file: {path}", file=sys.stderr)
            return 2
    report = compare_workbooks(a_path, b_path)
    print(format_report(report))
    return 0 if report.identical else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
