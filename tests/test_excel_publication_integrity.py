import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dart_crawler.excel_safe_publication as safe_publication
from dart_crawler.excel_export_result import Result as ExcelResult
from dart_crawler.excel_publication_file_ops import (
    CleanupCompleted,
    CleanupFailed,
    ExcelPublicationFileOps,
    FileOperationFailed,
    SystemExcelPublicationFileOps,
)
from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.excel_query_workbook_plan import ExcelWorkbookOptions
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import ErrorCode
from tests.excel_publication_test_support import (
    PostLinkCorruptionPublicationOps,
    PostLinkReplacementPublicationOps,
    capture_owned_file,
    install_move_other_owner_race,
)
from tests.excel_query_workbook_test_support import make_normalized_dataset
from tests.local_excel_export_test_support import RecordingClock


def test_source_replaced_inside_link_is_removed_when_identity_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_link = os.link
    replacement_payload = b"replacement-temp"

    def replace_source_then_link(source: Path, destination: Path) -> None:
        source.unlink()
        _ = source.write_bytes(replacement_payload)
        real_link(source, destination)

    monkeypatch.setattr(os, "link", replace_source_then_link)
    output_root = tmp_path / "output"

    result = _publish(output_root)

    final_path = output_root / "search_companies.xlsx"
    try:
        assert result.ok is False
        _assert_output_failure(result)
        assert not final_path.exists()
    finally:
        for replacement in output_root.glob(".search_companies.*.xlsx"):
            replacement.unlink(missing_ok=True)


def test_destination_replaced_before_capture_is_preserved_by_system_file_ops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_link = os.link
    source = tmp_path / "validated.xlsx"
    destination = tmp_path / "published.xlsx"
    replacement_payload = b"other-owner"
    _ = source.write_bytes(b"validated")

    def link_then_replace(source_path: Path, destination_path: Path) -> None:
        real_link(source_path, destination_path)
        destination_path.unlink()
        _ = destination_path.write_bytes(replacement_payload)

    monkeypatch.setattr(os, "link", link_then_replace)

    result = SystemExcelPublicationFileOps().publish_link(source, destination)

    assert isinstance(result, FileOperationFailed)
    assert destination.read_bytes() == replacement_payload


def test_unlink_owned_preserves_replacement_installed_during_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_replace = os.replace
    victim = tmp_path / "published.xlsx"
    replacement_payload = b"other-owner"
    _ = victim.write_bytes(b"owned")
    owned = capture_owned_file(victim)
    raced = False

    def replace_after_identity_check(
        source_path: Path,
        destination_path: Path,
    ) -> None:
        nonlocal raced
        if source_path == victim and not raced:
            raced = True
            source_path.unlink()
            _ = source_path.write_bytes(replacement_payload)
        real_replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", replace_after_identity_check)

    result = SystemExcelPublicationFileOps().unlink_owned(owned)

    assert raced
    assert isinstance(result, CleanupCompleted)
    assert victim.read_bytes() == replacement_payload
    assert not tuple(tmp_path.glob(".*.delete-*"))


def test_unlink_owned_preserves_quarantine_replaced_during_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_link = os.link
    victim = tmp_path / "published.xlsx"
    moved_payload = b"moved-other-owner"
    quarantine_replacement = b"quarantine-other-owner"
    _ = victim.write_bytes(b"owned")
    owned = capture_owned_file(victim)
    quarantines: list[Path] = []

    def restore_then_replace_quarantine(
        source_path: Path,
        destination_path: Path,
    ) -> None:
        real_link(source_path, destination_path)
        quarantines.append(source_path)
        source_path.unlink()
        _ = source_path.write_bytes(quarantine_replacement)

    install_move_other_owner_race(monkeypatch, victim, moved_payload)
    monkeypatch.setattr(os, "link", restore_then_replace_quarantine)

    result = SystemExcelPublicationFileOps().unlink_owned(owned)

    assert isinstance(result, CleanupCompleted)
    assert victim.read_bytes() == moved_payload
    assert [path.read_bytes() for path in quarantines] == [quarantine_replacement]


def test_unlink_owned_reports_failure_when_quarantine_replaced_before_restore_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_link = os.link
    victim = tmp_path / "published.xlsx"
    moved_payload = b"externally-deleted-owner"
    new_owner_payload = b"new-quarantine-owner"
    _ = victim.write_bytes(b"owned")
    owned = capture_owned_file(victim)
    quarantines: list[Path] = []

    def replace_quarantine_before_link(
        source_path: Path,
        destination_path: Path,
    ) -> None:
        quarantines.append(source_path)
        source_path.unlink()
        _ = source_path.write_bytes(new_owner_payload)
        real_link(source_path, destination_path)

    install_move_other_owner_race(monkeypatch, victim, moved_payload)
    monkeypatch.setattr(os, "link", replace_quarantine_before_link)

    result = SystemExcelPublicationFileOps().unlink_owned(owned)

    assert isinstance(result, CleanupFailed)
    assert [victim.read_bytes(), *(path.read_bytes() for path in quarantines)] == [new_owner_payload] * 2


def test_unlink_owned_preserves_both_files_when_restore_collides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_link = os.link
    victim = tmp_path / "published.xlsx"
    moved_payload = b"moved-other-owner"
    blocker_payload = b"new-path-owner"
    _ = victim.write_bytes(b"owned")
    owned = capture_owned_file(victim)
    quarantines: list[Path] = []

    def collide_with_restore(
        source_path: Path,
        destination_path: Path,
    ) -> None:
        quarantines.append(source_path)
        _ = destination_path.write_bytes(blocker_payload)
        real_link(source_path, destination_path)

    install_move_other_owner_race(monkeypatch, victim, moved_payload)
    monkeypatch.setattr(os, "link", collide_with_restore)

    result = SystemExcelPublicationFileOps().unlink_owned(owned)

    assert isinstance(result, CleanupFailed)
    assert victim.read_bytes() == blocker_payload
    assert [path.read_bytes() for path in quarantines] == [moved_payload]


def test_unlink_owned_close_failure_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_close = os.close
    victim = tmp_path / "published.xlsx"
    _ = victim.write_bytes(b"owned")
    owned = capture_owned_file(victim)
    close_calls = 0

    def close_once_then_reject_recursion(descriptor: int) -> None:
        nonlocal close_calls
        real_close(descriptor)
        close_calls += 1
        if close_calls > 1:
            msg = "cleanup recursively created another quarantine"
            raise AssertionError(msg)
        raise OSError

    monkeypatch.setattr(os, "close", close_once_then_reject_recursion)

    result = SystemExcelPublicationFileOps().unlink_owned(owned)

    assert isinstance(result, CleanupFailed)
    assert close_calls == 1
    assert victim.read_bytes() == b"owned"
    assert not tuple(tmp_path.glob(".*.delete-*"))


def test_replaced_destination_is_not_deleted_when_replaced_after_link(
    tmp_path: Path,
) -> None:
    replacement_payload = b"attacker-controlled-xlsx"
    operations = PostLinkReplacementPublicationOps(replacement_payload)
    output_root = tmp_path / "output"

    result = _publish(output_root, file_ops=operations)

    final_path = output_root / "search_companies.xlsx"
    try:
        assert result.ok is False
        assert result.error is not None
        assert result.error.code is ErrorCode.VALIDATION_FAILED
        assert result.error.details == {
            "reason": "excel_workbook_validation_failed"
        }
        assert final_path.read_bytes() == replacement_payload
    finally:
        final_path.unlink(missing_ok=True)


def test_published_workbook_is_revalidated_after_hardlink(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    operations = PostLinkCorruptionPublicationOps()

    result = _publish(output_root, file_ops=operations)

    final_path = output_root / "search_companies.xlsx"
    published_bytes = final_path.read_bytes() if final_path.exists() else None
    try:
        assert result.ok is False, (
            f"corrupted published workbook returned success: {published_bytes!r}"
        )
        assert result.error is not None
        assert result.error.code is ErrorCode.VALIDATION_FAILED
        assert result.error.details == {
            "reason": "excel_workbook_validation_failed"
        }
        assert not final_path.exists()
    finally:
        final_path.unlink(missing_ok=True)


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
