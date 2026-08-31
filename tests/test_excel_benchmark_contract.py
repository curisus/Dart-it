import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest
import scripts.excel_benchmark_worker as benchmark_worker
from pydantic import TypeAdapter

from dart_crawler.excel_export_result import Result as ExcelResult
from dart_crawler.excel_publication_file_ops import (
    SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    ExcelPublicationFileOps,
)
from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.excel_query_workbook_plan import (
    ExcelClock,
    ExcelWorkbookOptions,
)
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import ErrorCode, JsonObject, error_info

_JSON_OBJECT: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)
_WINDOWS_ONLY: Final = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows benchmark integration",
)


def _publication_failure(error_code: ErrorCode) -> ExcelResult[ExcelExportResult]:
    return ExcelResult[ExcelExportResult].failure(
        error_info(
            error_code,
            "Controlled test failure.",
            retryable=False,
            details={"reason": "controlled_test_failure"},
        )
    )


@pytest.mark.parametrize(
    ("failure_stage", "expected_reason"),
    [
        pytest.param("output_root", "xlsx_output_root_failed", id="output_root"),
        pytest.param("lock", "xlsx_lock_failed", id="lock"),
        pytest.param("temp", "xlsx_temp_failed", id="temp"),
        pytest.param("hardlink", "xlsx_hardlink_failed", id="hardlink"),
        pytest.param("validation", "xlsx_validation_failed", id="validation"),
    ],
)
def test_worker_reports_finite_xlsx_failure_stage(
    failure_stage: str,
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_publication(
        dataset: NormalizedExcelDataset,
        output_root: Path,
        *,
        clock: ExcelClock,
        options: ExcelWorkbookOptions,
        file_ops: ExcelPublicationFileOps = SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
        next_action: str | None = None,
    ) -> ExcelResult[ExcelExportResult]:
        del dataset, clock, options, next_action
        if failure_stage == "lock":
            _ = file_ops.acquire_lock(output_root / "candidate.xlsx.lock")
        elif failure_stage == "temp":
            _ = file_ops.create_temp(output_root, ".candidate.")
        elif failure_stage == "hardlink":
            _ = file_ops.publish_link(
                output_root / "source.xlsx",
                output_root / "destination.xlsx",
            )
        error_code = (
            ErrorCode.VALIDATION_FAILED
            if failure_stage == "validation"
            else ErrorCode.OUTPUT_WRITE_FAILED
        )
        return _publication_failure(error_code)

    monkeypatch.setattr(
        benchmark_worker,
        "publish_excel_dataset",
        fail_publication,
    )

    with pytest.raises(
        benchmark_worker.BenchmarkError,
        match=rf"^{expected_reason}$",
    ):
        _ = benchmark_worker.run_worker(2, 2)


def _run_benchmark(
    report_path: Path,
    workload: tuple[int, int, int],
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_count, row_count, column_count = workload
    script = Path("scripts/benchmark_excel_pipeline.py").resolve()
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script),
            "--runs",
            str(run_count),
            "--rows",
            str(row_count),
            "--columns",
            str(column_count),
            "--output",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )


@_WINDOWS_ONLY
def test_smoke_uses_pwsh_when_legacy_powershell_is_unavailable(
    tmp_path: Path,
) -> None:
    # Given: the CI platform tools expose PowerShell 7, but not legacy PowerShell.
    uv = shutil.which("uv")
    pwsh = shutil.which("pwsh.exe")
    assert uv is not None
    assert pwsh is not None
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        (str(Path(uv).parent), str(Path(pwsh).parent))
    )
    assert shutil.which("powershell.exe", path=environment["PATH"]) is None
    assert shutil.which("pwsh.exe", path=environment["PATH"]) is not None
    report_path = tmp_path / "benchmark.json"

    # When: the public benchmark entry point launches a real worker.
    completed = _run_benchmark(report_path, (1, 2, 2), environment)

    # Then: the worker measures RSS through pwsh and still writes its report.
    assert completed.returncode == 1, completed.stderr
    assert report_path.exists(), completed.stderr
    report = _JSON_OBJECT.validate_json(report_path.read_bytes())
    assert report["run_count"] == 1
    assert report["fresh_processes"] is True


@_WINDOWS_ONLY
def test_worker_failure_preserves_controlled_diagnostic(tmp_path: Path) -> None:
    # Given: uv is present, but neither supported PowerShell executable is on PATH.
    uv = shutil.which("uv")
    assert uv is not None
    environment = os.environ.copy()
    environment["PATH"] = str(Path(uv).parent)
    assert shutil.which("powershell.exe", path=environment["PATH"]) is None
    assert shutil.which("pwsh.exe", path=environment["PATH"]) is None
    report_path = tmp_path / "benchmark.json"

    # When: the public entry point launches its real worker.
    completed = _run_benchmark(report_path, (1, 2, 2), environment)

    # Then: no report is claimed and the controlled worker reason is retained.
    assert completed.returncode == 1
    assert not report_path.exists()
    assert completed.stderr.rstrip().endswith(
        "BenchmarkError: worker_failed:powershell_not_found"
    )


@_WINDOWS_ONLY
def test_worker_ignores_junction_temp_and_reaches_no_shell_failure(
    tmp_path: Path,
) -> None:
    # Given: ambient TEMP traverses a junction and no PowerShell is on PATH.
    uv = shutil.which("uv")
    assert uv is not None
    environment = os.environ.copy()
    environment["PATH"] = str(Path(uv).parent)
    assert shutil.which("powershell.exe", path=environment["PATH"]) is None
    assert shutil.which("pwsh.exe", path=environment["PATH"]) is None
    real_temp = tmp_path / "real-temp"
    real_temp.mkdir()
    junction_temp = tmp_path / "junction-temp"
    command_processor = Path(os.environ["COMSPEC"]).resolve(strict=True)
    completed_link = subprocess.run(  # noqa: S603
        [
            str(command_processor),
            "/c",
            "mklink",
            "/J",
            str(junction_temp),
            str(real_temp),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed_link.returncode == 0
    environment["TEMP"] = str(junction_temp)
    environment["TMP"] = str(junction_temp)
    report_path = tmp_path / "benchmark.json"

    # When: the real benchmark worker creates and reopens its XLSX.
    try:
        completed = _run_benchmark(report_path, (1, 2, 2), environment)
    finally:
        os.rmdir(junction_temp)

    # Then: it reaches the RSS stage instead of rejecting ambient TEMP.
    assert completed.returncode == 1
    assert not report_path.exists()
    assert completed.stderr.rstrip().endswith(
        "BenchmarkError: worker_failed:powershell_not_found"
    )
    assert "xlsx_output_root_failed" not in completed.stderr


@pytest.mark.parametrize(
    "worker_stderr_commands",
    [
        pytest.param(
            ("@echo benchmark_worker_error=FAKE_SECRET_VALUE 1>&2",),
            id="arbitrary_prefixed_value",
        ),
        pytest.param(
            ("@echo benchmark_worker_error= 1>&2",),
            id="empty_prefixed_value",
        ),
        pytest.param(
            (
                "@echo benchmark_worker_error=powershell_not_found 1>&2",
                "@echo benchmark_worker_error=normalization_failed 1>&2",
            ),
            id="multiple_prefixed_values",
        ),
    ],
)
@_WINDOWS_ONLY
def test_worker_failure_does_not_relay_untrusted_prefixed_stderr(
    tmp_path: Path,
    worker_stderr_commands: tuple[str, ...],
) -> None:
    # Given: the uv subprocess boundary emits an attacker-controlled prefixed value.
    fake_uv = tmp_path / "uv.cmd"
    _ = fake_uv.write_text(
        "\n".join((*worker_stderr_commands, "@exit /b 2", "")),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path)
    report_path = tmp_path / "benchmark.json"

    # When: the public benchmark entry point handles the failed worker launch.
    completed = _run_benchmark(report_path, (1, 2, 2), environment)

    # Then: the arbitrary value is neither relayed nor mistaken for an internal reason.
    assert completed.returncode == 1
    assert not report_path.exists()
    assert completed.stderr.rstrip().endswith("BenchmarkError: worker_failed")
    assert "FAKE_SECRET_VALUE" not in completed.stderr


@_WINDOWS_ONLY
def test_parent_preserves_finite_xlsx_stage_diagnostic(tmp_path: Path) -> None:
    # Given: the worker emits one finite, non-secret XLSX publication stage code.
    fake_uv = tmp_path / "uv.cmd"
    _ = fake_uv.write_text(
        "@echo benchmark_worker_error=xlsx_output_root_failed>&2\n@exit /b 2\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path)
    report_path = tmp_path / "benchmark.json"

    # When: the public benchmark entry point handles the failed worker launch.
    completed = _run_benchmark(report_path, (1, 2, 2), environment)

    # Then: that allowlisted static stage survives without relaying arbitrary stderr.
    assert completed.returncode == 1
    assert not report_path.exists()
    assert completed.stderr.rstrip().endswith(
        "BenchmarkError: worker_failed:xlsx_output_root_failed"
    )


@_WINDOWS_ONLY
def test_noncontract_smoke_uses_two_fresh_processes_without_claiming_pass(
    tmp_path: Path,
) -> None:
    # Given: a reduced deterministic dataset for a fast harness contract check.
    report_path = tmp_path / "benchmark.json"

    # When: the public benchmark entry point launches two fresh workers.
    completed = _run_benchmark(report_path, (2, 30, 4))

    # Then: it proves fresh workers without claiming the official contract passed.
    assert completed.returncode == 1, completed.stderr
    report = _JSON_OBJECT.validate_json(report_path.read_bytes())
    assert report["scenario"] == "excel_30_rows_4_columns"
    assert report["run_count"] == 2
    assert report["rows"] == 30
    assert report["columns"] == 4
    assert report["contract_configuration"] is False
    assert report["fresh_processes"] is True
    assert report["passed"] is False
    process_ids = report["process_ids"]
    assert isinstance(process_ids, list)
    assert len(process_ids) == len(set(process_ids)) == 2
    samples = report["samples"]
    assert isinstance(samples, list)
    assert len(samples) == 2
    sample = _JSON_OBJECT.validate_python(samples[0])
    timings = _JSON_OBJECT.validate_python(sample["seconds"])
    assert set(timings) == {
        "normalization",
        "page_selection_wire",
        "stateless_page_processing",
        "xlsx_generation",
    }
    checks = _JSON_OBJECT.validate_python(report["checks"])
    assert set(checks) == {
        "normalization",
        "page_selection_wire",
        "peak_rss",
        "stateless_page_processing",
        "xlsx_generation",
    }
