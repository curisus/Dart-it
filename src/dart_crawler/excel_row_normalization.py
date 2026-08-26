from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import assert_never

from dart_crawler.excel_canonical_json import canonical_json_text
from dart_crawler.excel_normalization_errors import NormalizationFailureReason
from dart_crawler.excel_page_models import ExcelRow, ExcelScalar
from dart_crawler.result import JsonValue

type ExcelSourceValue = (
    str
    | int
    | float
    | bool
    | bytes
    | list[ExcelSourceValue]
    | dict[str, ExcelSourceValue]
    | None
)
type SourcePairs = tuple[tuple[str, ExcelSourceValue], ...]


@unique
class ScalarKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NULL = "null"


@dataclass(frozen=True, slots=True)
class NormalizedCell:
    value: ExcelScalar
    scalar_kind: ScalarKind | None


@dataclass(frozen=True, slots=True)
class CellFailure:
    reason: NormalizationFailureReason


type CellResult = NormalizedCell | CellFailure


@dataclass(frozen=True, slots=True)
class PendingExcelRow:
    context: SourcePairs
    source: SourcePairs


@dataclass(frozen=True, slots=True)
class NormalizedExcelTable:
    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]


type TableResult = NormalizedExcelTable | CellFailure
type CellMap = dict[str, NormalizedCell]


@dataclass(frozen=True, slots=True)
class PreparedExcelRow:
    context: CellMap
    source: CellMap


@dataclass(frozen=True, slots=True)
class ColumnBinding:
    source_name: str
    target_name: str
    reuses_context: bool


def normalize_excel_cell(value: ExcelSourceValue) -> CellResult:
    match value:
        case bool() as boolean:
            return NormalizedCell(boolean, ScalarKind.BOOLEAN)
        case int() as integer:
            return NormalizedCell(integer, ScalarKind.INTEGER)
        case float() as number:
            if not math.isfinite(number):
                return CellFailure("non_finite_number")
            return NormalizedCell(number, ScalarKind.NUMBER)
        case str() as text:
            return NormalizedCell(text, ScalarKind.STRING)
        case None:
            return NormalizedCell(None, ScalarKind.NULL)
        case bytes():
            return CellFailure("unsupported_cell_value")
        case list() | dict():
            match _normalize_json_value(value):
                case CellFailure() as failure:
                    return failure
                case normalized:
                    return NormalizedCell(canonical_json_text(normalized), None)
        case unreachable:
            assert_never(unreachable)


def normalize_excel_rows(
    context_columns: tuple[str, ...],
    source_columns: tuple[str, ...],
    rows: tuple[PendingExcelRow, ...],
) -> TableResult:
    prepared_rows: list[PreparedExcelRow] = []
    ordered_source_columns = list(source_columns)
    seen_source_columns = set(source_columns)
    for row in rows:
        match _prepare_row(row):
            case CellFailure() as failure:
                return failure
            case PreparedExcelRow() as prepared:
                prepared_rows.append(prepared)
            case unreachable:
                assert_never(unreachable)
        for source_name, _value in row.source:
            if source_name not in seen_source_columns:
                ordered_source_columns.append(source_name)
                seen_source_columns.add(source_name)
    bindings = _column_bindings(
        context_columns,
        tuple(ordered_source_columns),
        tuple(prepared_rows),
    )
    final_columns = context_columns + tuple(
        binding.target_name for binding in bindings if not binding.reuses_context
    )
    normalized_rows = tuple(
        _finalize_row(final_columns, bindings, row) for row in prepared_rows
    )
    return NormalizedExcelTable(final_columns, normalized_rows)


def _normalize_json_value(value: ExcelSourceValue) -> JsonValue | CellFailure:
    match value:
        case bool() | int() | str() | None:
            return value
        case float() as number:
            if not math.isfinite(number):
                return CellFailure("non_finite_number")
            return number
        case bytes():
            return CellFailure("unsupported_cell_value")
        case list() as items:
            return _normalize_json_list(items)
        case dict() as mapping:
            return _normalize_json_mapping(mapping)
        case unreachable:
            assert_never(unreachable)


def _normalize_json_list(
    items: list[ExcelSourceValue],
) -> list[JsonValue] | CellFailure:
    normalized_items: list[JsonValue] = []
    for item in items:
        match _normalize_json_value(item):
            case CellFailure() as failure:
                return failure
            case normalized:
                normalized_items.append(normalized)
    return normalized_items


def _normalize_json_mapping(
    mapping: dict[str, ExcelSourceValue],
) -> dict[str, JsonValue] | CellFailure:
    normalized_mapping: dict[str, JsonValue] = {}
    for key, item in mapping.items():
        match _normalize_json_value(item):
            case CellFailure() as failure:
                return failure
            case normalized:
                normalized_mapping[key] = normalized
    return normalized_mapping


def _prepare_row(row: PendingExcelRow) -> PreparedExcelRow | CellFailure:
    match _prepare_pairs(row.context):
        case CellFailure() as failure:
            return failure
        case dict() as context:
            pass
        case unreachable:
            assert_never(unreachable)
    match _prepare_pairs(row.source):
        case CellFailure() as failure:
            return failure
        case dict() as source:
            return PreparedExcelRow(context, source)
        case unreachable:
            assert_never(unreachable)


def _prepare_pairs(pairs: SourcePairs) -> CellMap | CellFailure:
    prepared: CellMap = {}
    for name, value in pairs:
        match normalize_excel_cell(value):
            case CellFailure() as failure:
                return failure
            case NormalizedCell() as normalized:
                prepared[name] = normalized
            case unreachable:
                assert_never(unreachable)
    return prepared


def _column_bindings(
    context_columns: tuple[str, ...],
    source_columns: tuple[str, ...],
    rows: tuple[PreparedExcelRow, ...],
) -> tuple[ColumnBinding, ...]:
    occupied = set(context_columns) | {
        source_name
        for source_name in source_columns
        if source_name not in context_columns
    }
    bindings: list[ColumnBinding] = []
    for source_name in source_columns:
        reuses_context = source_name in context_columns and _matches_context(
            source_name, rows
        )
        target_name = source_name
        if source_name in context_columns and not reuses_context:
            target_name = _available_source_name(source_name, occupied)
        bindings.append(ColumnBinding(source_name, target_name, reuses_context))
        if not reuses_context:
            occupied.add(target_name)
    return tuple(bindings)


def _matches_context(
    source_name: str,
    rows: tuple[PreparedExcelRow, ...],
) -> bool:
    for row in rows:
        source_cell = row.source.get(source_name)
        if source_cell is None:
            continue
        context_cell = row.context[source_name]
        if (
            source_cell.scalar_kind is None
            or source_cell.scalar_kind is not context_cell.scalar_kind
            or source_cell.value != context_cell.value
        ):
            return False
    return True


def _available_source_name(source_name: str, occupied: set[str]) -> str:
    candidate = f"source_{source_name}"
    suffix = 2
    while candidate in occupied:
        candidate = f"source_{source_name}_{suffix}"
        suffix += 1
    return candidate


def _finalize_row(
    columns: tuple[str, ...],
    bindings: tuple[ColumnBinding, ...],
    row: PreparedExcelRow,
) -> ExcelRow:
    values: ExcelRow = {
        column: row.context[column].value for column in row.context
    }
    for binding in bindings:
        if binding.reuses_context:
            continue
        source_cell = row.source.get(binding.source_name)
        values[binding.target_name] = (
            None if source_cell is None else source_cell.value
        )
    return {column: values[column] for column in columns}
