from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from dart_crawler.excel_canonical_json import canonical_json_text
from dart_crawler.excel_json_models import model_json_object
from dart_crawler.excel_numeric_columns import numeric_column_formats
from dart_crawler.excel_page_models import ExcelScalar
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import JsonValue

EXCEL_DATA_ROWS_PER_SHEET: Final = 1_048_575
EXCEL_MAX_COLUMNS: Final = 16_384

type WorkbookRow = tuple[ExcelScalar, ...]


class ExcelClock(Protocol):
    def now_utc(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class SystemExcelClock:
    def now_utc(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ExcelWorkbookOptions:
    data_rows_per_sheet: int = EXCEL_DATA_ROWS_PER_SHEET


@dataclass(frozen=True, slots=True)
class ExcelWorkbookPlan:
    dataset: NormalizedExcelDataset
    data_sheet_names: tuple[str, ...]
    generated_at_utc: str
    options: ExcelWorkbookOptions
    # One display format per data column, aligned with dataset.columns and
    # computed once: writing applies it and validation re-reads it, each per
    # sheet and validation twice per file, so deriving it here keeps a workbook
    # from being scanned four times for an answer that cannot change.
    column_number_formats: tuple[str | None, ...] = ()

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return (*self.data_sheet_names, "metadata", "warnings")


def build_excel_workbook_plan(
    dataset: NormalizedExcelDataset,
    clock: ExcelClock,
    options: ExcelWorkbookOptions,
) -> ExcelWorkbookPlan:
    sheet_count = max(
        1,
        (dataset.total_rows + options.data_rows_per_sheet - 1)
        // options.data_rows_per_sheet,
    )
    data_sheet_names = tuple(
        "data" if index == 0 else f"data_{index + 1}"
        for index in range(sheet_count)
    )
    instant = clock.now_utc()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    generated = instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    formats = numeric_column_formats(dataset.numeric_columns, dataset.rows)
    return ExcelWorkbookPlan(
        dataset=dataset,
        data_sheet_names=data_sheet_names,
        generated_at_utc=generated,
        options=options,
        column_number_formats=tuple(
            formats.get(column) for column in dataset.columns
        ),
    )


def metadata_rows(plan: ExcelWorkbookPlan) -> tuple[WorkbookRow, ...]:
    dataset = plan.dataset
    return (
        ("key", "value"),
        ("schema_version", dataset.schema_version),
        ("domain", dataset.domain.value),
        # One row per request argument, so the sheet answers "which year, which
        # company, consolidated or separate" without decoding a fingerprint.
        *(
            (f"argument.{name}", _argument_value(value))
            for name, value in dataset.validated_arguments.items()
        ),
        ("request_fingerprint", dataset.request_fingerprint),
        ("source_fingerprint", dataset.source_fingerprint),
        ("dataset_id", dataset.dataset_id),
        ("total_rows", dataset.total_rows),
        ("generated_at_utc", plan.generated_at_utc),
        ("provenance", canonical_json_text(model_json_object(dataset.provenance))),
        ("data_sheet_names", canonical_json_text(list(plan.data_sheet_names))),
    )


def _argument_value(value: JsonValue) -> ExcelScalar:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return canonical_json_text(value)


def warning_rows(plan: ExcelWorkbookPlan) -> tuple[WorkbookRow, ...]:
    rows: list[WorkbookRow] = [
        ("warning_index", "code", "message", "details")
    ]
    rows.extend(
        (
            index,
            warning.code.value,
            warning.message,
            canonical_json_text(warning.details),
        )
        for index, warning in enumerate(plan.dataset.warnings, start=1)
    )
    return tuple(rows)
