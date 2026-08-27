import errno
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dart_crawler.excel_query_workbook_writer as workbook_writer
import dart_crawler.excel_safe_publication as safe_publication
from dart_crawler.excel_export_result import Result as ExcelResult
from dart_crawler.excel_publication_file_ops import ExcelPublicationFileOps
from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.excel_query_workbook_plan import (
    ExcelWorkbookOptions,
    ExcelWorkbookPlan,
)
from dart_crawler.excel_query_workbook_writer import WorkbookWriteOutcome
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import ErrorCode
from tests.excel_publication_test_support import (
    LinkFailurePublicationOps,
    LockFailurePublicationOps,
    ReplacementRacePublicationOps,
    UnsafeTempPublicationOps,
)
from tests.excel_query_workbook_test_support import make_normalized_dataset
from tests.local_excel_export_test_support import RecordingClock


def test_non_directory_and_symlink_output_roots_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    symlink_root = tmp_path / "symlink-root"
    symlink_root.symlink_to(target, target_is_directory=True)
    file_root = tmp_path / "file-root"
    _ = file_root.write_text("not a directory", encoding="utf-8")

    for configured in (symlink_root, symlink_root / "child", file_root):
        result = _publish(configured)
        _assert_output_failure(result)

    assert list(target.iterdir()) == []
    assert file_root.read_text(encoding="utf-8") == "not a directory"


def test_windows_junction_output_root_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "junction-root"
    command_processor = Path(os.environ["COMSPEC"]).resolve(strict=True)
    completed = subprocess.run(  # noqa: S603
        [
            str(command_processor),
            "/c",
            "mklink",
            "/J",
            str(junction),
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    try:
        _assert_output_failure(_publish(junction))
        assert list(target.iterdir()) == []
    finally:
        os.rmdir(junction)


@pytest.mark.parametrize("candidate_kind", ["final", "lock"])
def test_candidate_symlinks_are_rejected_without_touching_target(
    candidate_kind: str,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    target = tmp_path / "outside-target"
    _ = target.write_bytes(b"outside")
    final_path = output_root / "search_companies.xlsx"
    candidate = final_path if candidate_kind == "final" else final_path.with_suffix(
        ".xlsx.lock"
    )
    candidate.symlink_to(target)

    result = _publish(output_root)

    _assert_output_failure(result)
    assert target.read_bytes() == b"outside"


def test_unsafe_temp_escape_is_rejected_and_owned_paths_are_cleaned(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    outside_temp = tmp_path / "outside-temp.xlsx"
    operations = UnsafeTempPublicationOps(outside_temp)

    result = _publish(output_root, file_ops=operations)

    _assert_output_failure(result)
    assert not outside_temp.exists()
    assert list(output_root.iterdir()) == []


def test_lock_permission_failure_is_not_misclassified_as_name_collision(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"

    result = _publish(output_root, file_ops=LockFailurePublicationOps())

    _assert_output_failure(result)
    assert list(output_root.iterdir()) == []


@pytest.mark.parametrize(
    "link_error",
    [PermissionError(errno.EACCES, "denied"), OSError(errno.EXDEV, "cross-device")],
)
def test_hardlink_permission_and_unsupported_errors_have_no_fallback(
    link_error: OSError,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_link(source: Path, destination: Path) -> None:
        del source, destination
        raise link_error

    monkeypatch.setattr(os, "link", fail_link)
    output_root = tmp_path / "output"

    result = _publish(output_root)

    _assert_output_failure(result)
    assert list(output_root.iterdir()) == []


def test_corrupted_temp_fails_reopen_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_writer = workbook_writer.write_excel_query_workbook

    def write_then_corrupt(
        path: Path,
        plan: ExcelWorkbookPlan,
    ) -> WorkbookWriteOutcome:
        outcome = original_writer(path, plan)
        assert path.write_bytes(b"not-an-xlsx") == 11
        return outcome

    monkeypatch.setattr(
        workbook_writer,
        "write_excel_query_workbook",
        write_then_corrupt,
    )
    output_root = tmp_path / "output"

    result = _publish(output_root)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.VALIDATION_FAILED
    assert result.error.details == {"reason": "excel_workbook_validation_failed"}
    assert list(output_root.iterdir()) == []


def test_prepublication_failure_removes_only_owned_temp_and_lock(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    sentinel = output_root / "unrelated.txt"
    _ = sentinel.write_bytes(b"preserve")

    result = _publish(output_root, file_ops=LinkFailurePublicationOps())

    _assert_output_failure(result)
    assert sentinel.read_bytes() == b"preserve"
    assert list(output_root.iterdir()) == [sentinel]


def test_cleanup_never_deletes_paths_replaced_by_another_owner(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    operations = ReplacementRacePublicationOps()

    result = _publish(output_root, file_ops=operations)

    _assert_output_failure(result)
    assert operations.replacement_temp is not None
    assert operations.replacement_lock is not None
    assert operations.replacement_temp.read_bytes() == b"replacement-temp"
    assert operations.replacement_lock.read_bytes() == b"replacement-lock"
    operations.replacement_temp.unlink()
    operations.replacement_lock.unlink()


def _publish(
    output_root: Path,
    *,
    file_ops: ExcelPublicationFileOps | None = None,
) -> ExcelResult[ExcelExportResult]:
    dataset: NormalizedExcelDataset = make_normalized_dataset(("value",), ())
    clock = RecordingClock(datetime(2026, 7, 8, tzinfo=UTC))
    options = ExcelWorkbookOptions()
    if file_ops is None:
        return safe_publication.publish_excel_dataset(
            dataset,
            output_root,
            clock=clock,
            options=options,
        )
    return safe_publication.publish_excel_dataset(
        dataset,
        output_root,
        file_ops=file_ops,
        clock=clock,
        options=options,
    )


def _assert_output_failure(result: ExcelResult[ExcelExportResult]) -> None:
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.OUTPUT_WRITE_FAILED
    assert result.error.retryable is False
    assert result.error.details == {"reason": "output_write_failed"}
