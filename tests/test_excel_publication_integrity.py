import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dart_crawler.excel_safe_publication as safe_publication
from dart_crawler.excel_export_result import Result as ExcelResult
from dart_crawler.excel_publication_file_ops import ExcelPublicationFileOps
from dart_crawler.excel_query_export_models import ExcelExportResult
from dart_crawler.excel_query_workbook_plan import ExcelWorkbookOptions
from dart_crawler.normalized_excel_models import NormalizedExcelDataset
from dart_crawler.result import ErrorCode
from tests.excel_publication_test_support import (
    PostLinkCorruptionPublicationOps,
    PostLinkReplacementPublicationOps,
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
