from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from dart_crawler.excel_publication_file_ops import (
    SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    CleanupOutcome,
    ExcelPublicationFileOps,
    LinkOutcome,
    LockOutcome,
    OwnedFile,
    TempOutcome,
)


class XlsxFailureStage(StrEnum):
    OUTPUT_ROOT = "xlsx_output_root_failed"
    LOCK = "xlsx_lock_failed"
    TEMP = "xlsx_temp_failed"
    HARDLINK = "xlsx_hardlink_failed"


class DiagnosingPublicationFileOps:
    def __init__(
        self,
        delegate: ExcelPublicationFileOps = SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    ) -> None:
        self._delegate: ExcelPublicationFileOps = delegate
        self.failure_stage: XlsxFailureStage = XlsxFailureStage.OUTPUT_ROOT

    def acquire_lock(self, path: Path) -> LockOutcome:
        self.failure_stage = XlsxFailureStage.LOCK
        return self._delegate.acquire_lock(path)

    def create_temp(self, directory: Path, prefix: str) -> TempOutcome:
        self.failure_stage = XlsxFailureStage.TEMP
        return self._delegate.create_temp(directory, prefix)

    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.failure_stage = XlsxFailureStage.HARDLINK
        return self._delegate.publish_link(source, destination)

    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome:
        return self._delegate.unlink_owned(file)
