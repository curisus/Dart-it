#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#     "pydantic==2.13.4",
# ]
# ///

# ─── How to run ───
# 1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
# 2. Run: uv run --script scripts/benchmark_excel_pipeline.py --output benchmark.json
# ──────────────────

from __future__ import annotations

import argparse
import shutil
import statistics
import subprocess
from pathlib import Path
from typing import ClassVar, Final, Never

from pydantic import BaseModel, ConfigDict, Field

_NORMALIZATION_LIMIT: Final = 10.0
_PAGE_WIRE_LIMIT: Final = 1.0
_XLSX_LIMIT: Final = 15.0
_STATELESS_LIMIT: Final = 11.0
_RSS_LIMIT: Final = 512.0


class Seconds(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    normalization: float
    page_selection_wire: float
    xlsx_generation: float
    stateless_page_processing: float


class WorkerEnvironment(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    python: str
    implementation: str
    platform: str
    machine: str
    processor: str
    cpu_count: int | None
    mcp: str
    openpyxl: str
    pydantic: str


class WorkerSample(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    process_id: int
    rows: int
    columns: int
    seconds: Seconds
    peak_rss_mib: float
    wire_bytes: int
    environment: WorkerEnvironment


class BenchmarkChecks(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    normalization: bool
    page_selection_wire: bool
    xlsx_generation: bool
    stateless_page_processing: bool
    peak_rss: bool


class BenchmarkLimits(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    normalization_seconds: float
    page_selection_wire_seconds: float
    xlsx_generation_seconds: float
    stateless_page_processing_seconds: float
    peak_rss_mib: float


class BenchmarkReport(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    scenario: str
    run_count: int
    rows: int
    columns: int
    contract_configuration: bool
    fresh_processes: bool
    process_ids: tuple[int, ...]
    environment: WorkerEnvironment
    samples: tuple[WorkerSample, ...]
    medians_seconds: Seconds
    peak_rss_mib_max: float
    limits: BenchmarkLimits
    checks: BenchmarkChecks
    passed: bool


class BenchmarkArguments(BaseModel):
    runs: int = Field(default=3, gt=0)
    rows: int = Field(default=10_000, gt=0)
    columns: int = Field(default=20, gt=0)
    output: Path


class BenchmarkError(RuntimeError):
    pass


def _fail(reason: str) -> Never:
    raise BenchmarkError(reason)


def _worker_sample(worker: Path, row_count: int, column_count: int) -> WorkerSample:
    uv = shutil.which("uv")
    if uv is None:
        _fail("uv_not_found")
    completed = subprocess.run(  # noqa: S603
        [
            uv,
            "run",
            "--script",
            str(worker),
            "--rows",
            str(row_count),
            "--columns",
            str(column_count),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _fail("worker_failed")
    return WorkerSample.model_validate_json(completed.stdout)


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def run_benchmark(
    *,
    run_count: int,
    row_count: int,
    column_count: int,
) -> BenchmarkReport:
    worker = Path(__file__).with_name("excel_benchmark_worker.py")
    samples = [
        _worker_sample(worker, row_count, column_count)
        for _ in range(run_count)
    ]
    medians = Seconds(
        normalization=_median(
            [sample.seconds.normalization for sample in samples]
        ),
        page_selection_wire=_median(
            [sample.seconds.page_selection_wire for sample in samples]
        ),
        xlsx_generation=_median(
            [sample.seconds.xlsx_generation for sample in samples]
        ),
        stateless_page_processing=_median(
            [sample.seconds.stateless_page_processing for sample in samples]
        ),
    )
    peak_rss_mib = max(sample.peak_rss_mib for sample in samples)
    process_ids = [sample.process_id for sample in samples]
    fresh_processes = len(set(process_ids)) == run_count
    contract_configuration = (
        run_count == 3 and row_count == 10_000 and column_count == 20
    )
    checks = BenchmarkChecks(
        normalization=medians.normalization <= _NORMALIZATION_LIMIT,
        page_selection_wire=(
            medians.page_selection_wire <= _PAGE_WIRE_LIMIT
        ),
        xlsx_generation=medians.xlsx_generation <= _XLSX_LIMIT,
        stateless_page_processing=(
            medians.stateless_page_processing <= _STATELESS_LIMIT
        ),
        peak_rss=peak_rss_mib <= _RSS_LIMIT,
    )
    passed = contract_configuration and fresh_processes and all(
        (
            checks.normalization,
            checks.page_selection_wire,
            checks.xlsx_generation,
            checks.stateless_page_processing,
            checks.peak_rss,
        )
    )
    return BenchmarkReport(
        schema_version=1,
        scenario=f"excel_{row_count}_rows_{column_count}_columns",
        run_count=run_count,
        rows=row_count,
        columns=column_count,
        contract_configuration=contract_configuration,
        fresh_processes=fresh_processes,
        process_ids=tuple(process_ids),
        environment=samples[0].environment,
        samples=tuple(samples),
        medians_seconds=medians,
        peak_rss_mib_max=peak_rss_mib,
        limits=BenchmarkLimits(
            normalization_seconds=_NORMALIZATION_LIMIT,
            page_selection_wire_seconds=_PAGE_WIRE_LIMIT,
            xlsx_generation_seconds=_XLSX_LIMIT,
            stateless_page_processing_seconds=_STATELESS_LIMIT,
            peak_rss_mib=_RSS_LIMIT,
        ),
        checks=checks,
        passed=passed,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--runs", type=int, default=3)
    _ = parser.add_argument("--rows", type=int, default=10_000)
    _ = parser.add_argument("--columns", type=int, default=20)
    _ = parser.add_argument("--output", type=Path, required=True)
    arguments = BenchmarkArguments.model_validate(vars(parser.parse_args()))
    report = run_benchmark(
        run_count=arguments.runs,
        row_count=arguments.rows,
        column_count=arguments.columns,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = report.model_dump_json(indent=2)
    arguments.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
