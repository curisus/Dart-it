#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#     "mcp==2.0.0",
#     "openpyxl==3.1.5",
#     "pydantic==2.13.4",
# ]
# ///

# ─── How to run ───
# 1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
# 2. Run: uv run --script scripts/excel_benchmark_worker.py --rows 10000 --columns 20
# ──────────────────

from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Final, Never

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pydantic import BaseModel, SecretBytes  # noqa: E402

from dart_crawler.excel_company_arguments import (  # noqa: E402
    SearchCompaniesArguments,
)
from dart_crawler.excel_cursor import CursorSecret  # noqa: E402
from dart_crawler.excel_dataset_builder import (  # noqa: E402
    ExcelSourceDataset,
    normalize_excel_source,
)
from dart_crawler.excel_page_models import (  # noqa: E402
    ExcelDataDomain,
    ExcelProvenance,
)
from dart_crawler.excel_page_selection import (  # noqa: E402
    ExcelPageSelection,
    select_excel_page,
)
from dart_crawler.excel_page_selection import (  # noqa: E402
    NormalizedExcelDataset as PageDataset,
)
from dart_crawler.excel_query_workbook_plan import (  # noqa: E402
    ExcelWorkbookOptions,
    SystemExcelClock,
)
from dart_crawler.excel_row_normalization import (  # noqa: E402
    PendingExcelRow,
)
from dart_crawler.excel_safe_publication import (  # noqa: E402
    publish_excel_dataset,
)
from dart_crawler.mcp_wire import measure_excel_result_wire  # noqa: E402
from dart_crawler.normalized_excel_models import (  # noqa: E402
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import JsonObject  # noqa: E402

_MIB: Final = 1024 * 1024
_CURSOR_SECRET: Final = CursorSecret(value=SecretBytes(b"benchmark-secret" * 3))


class BenchmarkError(RuntimeError):
    pass


class WorkerArguments(BaseModel):
    rows: int
    columns: int

def _fail(reason: str) -> Never:
    raise BenchmarkError(reason)


def _build_source(row_count: int, column_count: int) -> ExcelSourceDataset:
    columns = tuple(f"column_{index:02d}" for index in range(column_count))
    rows = tuple(
        PendingExcelRow(
            context=(),
            source=tuple(
                (column, row_index * column_count + column_index)
                for column_index, column in enumerate(columns)
            ),
        )
        for row_index in range(row_count)
    )
    provenance = NormalizedExcelProvenance(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        source_rows=row_count,
        normalized_rows=row_count,
    )
    return ExcelSourceDataset(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments=SearchCompaniesArguments(company_query="benchmark"),
        context_columns=(),
        source_columns=columns,
        rows=rows,
        warnings=(),
        provenance=provenance,
    )


def _normalize(source: ExcelSourceDataset) -> NormalizedExcelDataset:
    result = normalize_excel_source(source)
    dataset = result.data
    if dataset is None:
        _fail("normalization_failed")
    return dataset


def _select_and_serialize(dataset: NormalizedExcelDataset) -> int:
    page_dataset = PageDataset(
        columns=dataset.columns,
        rows=dataset.rows,
        source_fingerprint=dataset.source_fingerprint,
        warnings=dataset.warnings,
        provenance=ExcelProvenance(
            source=dataset.provenance.source,
            source_fingerprint=dataset.source_fingerprint,
        ),
    )
    page_result = select_excel_page(
        ExcelPageSelection(
            dataset=page_dataset,
            domain=dataset.domain,
            request_fingerprint=dataset.request_fingerprint,
            row_offset=0,
            page_index=0,
            page_size=1_000,
            cursor_secret=_CURSOR_SECRET,
        )
    )
    if page_result.data is None:
        _fail("page_selection_failed")
    maximum_bytes = measure_excel_result_wire(page_result).maximum_bytes
    if maximum_bytes <= 0:
        _fail("wire_serialization_failed")
    return maximum_bytes


def _peak_rss_mib() -> float:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        _fail("powershell_not_found")
    completed = subprocess.run(  # noqa: S603
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"[System.Diagnostics.Process]::GetProcessById({os.getpid()}).PeakWorkingSet64",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _fail("peak_rss_measurement_failed")
    try:
        return int(completed.stdout.strip()) / _MIB
    except ValueError:
        _fail("peak_rss_measurement_failed")


def run_worker(row_count: int, column_count: int) -> JsonObject:
    source = _build_source(row_count, column_count)

    started = time.perf_counter()
    dataset = _normalize(source)
    normalization_seconds = time.perf_counter() - started

    started = time.perf_counter()
    wire_bytes = _select_and_serialize(dataset)
    page_seconds = time.perf_counter() - started

    with tempfile.TemporaryDirectory(prefix="dart_excel_benchmark_") as temp_dir:
        started = time.perf_counter()
        export_result = publish_excel_dataset(
            dataset,
            Path(temp_dir) / "output",
            clock=SystemExcelClock(),
            options=ExcelWorkbookOptions(),
        )
        xlsx_seconds = time.perf_counter() - started
        if export_result.data is None:
            _fail("xlsx_generation_failed")

    del dataset
    _ = gc.collect()
    started = time.perf_counter()
    stateless_dataset = _normalize(source)
    stateless_wire_bytes = _select_and_serialize(stateless_dataset)
    stateless_seconds = time.perf_counter() - started
    if stateless_wire_bytes != wire_bytes:
        _fail("wire_measurement_changed")

    return {
        "process_id": os.getpid(),
        "rows": row_count,
        "columns": column_count,
        "seconds": {
            "normalization": normalization_seconds,
            "page_selection_wire": page_seconds,
            "xlsx_generation": xlsx_seconds,
            "stateless_page_processing": stateless_seconds,
        },
        "peak_rss_mib": _peak_rss_mib(),
        "wire_bytes": wire_bytes,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "mcp": importlib.metadata.version("mcp"),
            "openpyxl": importlib.metadata.version("openpyxl"),
            "pydantic": importlib.metadata.version("pydantic"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--rows", type=int, required=True)
    _ = parser.add_argument("--columns", type=int, required=True)
    arguments = WorkerArguments.model_validate(vars(parser.parse_args()))
    sample = run_worker(arguments.rows, arguments.columns)
    print(json.dumps(sample, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
