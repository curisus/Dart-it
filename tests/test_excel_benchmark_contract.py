import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest
from pydantic import TypeAdapter

from dart_crawler.result import JsonObject

_JSON_OBJECT: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)


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
