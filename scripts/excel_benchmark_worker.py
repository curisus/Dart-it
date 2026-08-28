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
from enum import StrEnum
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
from dart_crawler.excel_publication_file_ops import (  # noqa: E402
    SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    CleanupOutcome,
    ExcelPublicationFileOps,
    LinkOutcome,
    LockOutcome,
    OwnedFile,
    TempOutcome,
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
from dart_crawler.result import ErrorCode, JsonObject  # noqa: E402

_MIB: Final = 1024 * 1024
_CURSOR_SECRET: Final = CursorSecret(value=SecretBytes(b"benchmark-secret" * 3))


class BenchmarkError(RuntimeError):
    pass


class WorkerArguments(BaseModel):
    rows: int
    columns: int


class _XlsxFailureStage(StrEnum):
    OUTPUT_ROOT = "xlsx_output_root_failed"
    LOCK = "xlsx_lock_failed"
    TEMP = "xlsx_temp_failed"
    HARDLINK = "xlsx_hardlink_failed"


class _DiagnosingPublicationFileOps:
    def __init__(
        self,
        delegate: ExcelPublicationFileOps = SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    ) -> None:
        self._delegate: ExcelPublicationFileOps = delegate
        self.failure_stage: _XlsxFailureStage = _XlsxFailureStage.OUTPUT_ROOT

    def acquire_lock(self, path: Path) -> LockOutcome:
        self.failure_stage = _XlsxFailureStage.LOCK
        return self._delegate.acquire_lock(path)

    def create_temp(self, directory: Path, prefix: str) -> TempOutcome:
        self.failure_stage = _XlsxFailureStage.TEMP
        return self._delegate.create_temp(directory, prefix)

    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.failure_stage = _XlsxFailureStage.HARDLINK
        return self._delegate.publish_link(source, destination)

    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome:
        return self._delegate.unlink_owned(file)


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
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
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

    with tempfile.TemporaryDirectory(
        dir=_PROJECT_ROOT,
        prefix=".dart_excel_benchmark_",
    ) as temp_dir:
        started = time.perf_counter()
        publication_ops = _DiagnosingPublicationFileOps()
        export_result = publish_excel_dataset(
            dataset,
            Path(temp_dir) / "output",
            clock=SystemExcelClock(),
            options=ExcelWorkbookOptions(),
            file_ops=publication_ops,
        )
        xlsx_seconds = time.perf_counter() - started
        if export_result.data is None:
            if (
                export_result.error is not None
                and export_result.error.code is ErrorCode.VALIDATION_FAILED
            ):
                _fail("xlsx_validation_failed")
            _fail(publication_ops.failure_stage.value)

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
    try:
        sample = run_worker(arguments.rows, arguments.columns)
    except BenchmarkError as error:
        print(f"benchmark_worker_error={error}", file=sys.stderr)
        return 2
    print(json.dumps(sample, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
