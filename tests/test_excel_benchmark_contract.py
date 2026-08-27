import subprocess
import sys
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from dart_crawler.result import JsonObject

_JSON_OBJECT: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)


def test_noncontract_smoke_uses_two_fresh_processes_without_claiming_pass(
    tmp_path: Path,
) -> None:
    # Given: a reduced deterministic dataset for a fast harness contract check.
    script = Path("scripts/benchmark_excel_pipeline.py").resolve()
    report_path = tmp_path / "benchmark.json"

    # When: the public benchmark entry point launches two fresh workers.
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script),
            "--runs",
            "2",
            "--rows",
            "30",
            "--columns",
            "4",
            "--output",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

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
