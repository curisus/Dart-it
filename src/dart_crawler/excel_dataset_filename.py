"""Name a query export after the request that produced it.

Five yearly exports into one folder used to be `get_financial_statements.xlsx`
through `_5.xlsx`, so telling FY2021 from FY2025 meant opening each file. The
request arguments go into the name instead, and the numbered suffix stays for
genuine collisions.
"""

from __future__ import annotations

from typing import Final

from dart_crawler.filename_safety import MAX_FILENAME_STEM_CHARS, safe_filename
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import JsonValue

# Long free-text arguments (a company query) would push the identifying values
# past the filename limit, so each part contributes a bounded amount.
_MAX_PART_CHARS: Final = 40
# Room the collision suffix needs, reserved before the stem is trimmed so that
# _2 and _3 cannot be cut off and collapse every candidate into one name.
_SUFFIX_RESERVE_CHARS: Final = 8
_MAX_STEM_CHARS: Final = MAX_FILENAME_STEM_CHARS - _SUFFIX_RESERVE_CHARS
# A list argument names the companies, topics, or event types the export is
# about, which is exactly what distinguishes two files of the same domain. Only
# the first few reach the name; the metadata sheet holds the full list.
_MAX_LIST_ITEMS: Final = 3


def dataset_filename(dataset: NormalizedExcelDataset, suffix: int) -> str:
    """Return the workbook name for one dataset and collision number."""
    stem = dataset_filename_stem(dataset)[:_MAX_STEM_CHARS]
    numbered = stem if suffix == 1 else f"{stem}_{suffix}"
    return safe_filename(f"{numbered}.xlsx")


def dataset_filename_stem(dataset: NormalizedExcelDataset) -> str:
    """Return the domain followed by its request arguments in field order."""
    parts = [dataset.domain.value]
    parts.extend(
        part
        for part in (
            _argument_part(value) for value in dataset.validated_arguments.values()
        )
        if part
    )
    return "_".join(parts)


def _argument_part(value: JsonValue) -> str:
    if isinstance(value, list):
        return _list_part(value)
    return _scalar_part(value)


def _list_part(values: list[JsonValue]) -> str:
    parts = [part for part in map(_scalar_part, values[:_MAX_LIST_ITEMS]) if part]
    if not parts:
        return ""
    # "외3" tells a reader the file covers more than the names it shows, so two
    # exports of overlapping company sets are not mistaken for the same request.
    if len(values) > len(parts):
        parts.append(f"외{len(values) - len(parts)}")
    return "-".join(parts)


def _scalar_part(value: JsonValue) -> str:
    # A dict identifies nothing readable in a name and the metadata sheet
    # records it in full, so it is left out.
    if isinstance(value, bool) or value is None or isinstance(value, dict):
        return ""
    if isinstance(value, (int, float)):
        # Bounded like the text parts: an unbounded integer argument would
        # otherwise fill the name and leave no room for the collision suffix.
        return str(value)[:_MAX_PART_CHARS]
    if not isinstance(value, str):
        return ""
    return "_".join(value.split())[:_MAX_PART_CHARS]
