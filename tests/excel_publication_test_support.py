import os
from pathlib import Path
from typing import override

import pytest

from dart_crawler.excel_publication_file_ops import (
    SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    CandidateUnavailable,
    CleanupFailed,
    CleanupOutcome,
    ExcelPublicationFileOps,
    FileIdentity,
    FileOperationFailed,
    HardLinkPublished,
    LinkOutcome,
    LockAcquired,
    LockOutcome,
    OwnedFile,
    TempFileCreated,
    TempOutcome,
)


class RecordingPublicationOps:
    def __init__(
        self,
        delegate: ExcelPublicationFileOps = SYSTEM_EXCEL_PUBLICATION_FILE_OPS,
    ) -> None:
        self._delegate: ExcelPublicationFileOps = delegate
        self.temp_paths: list[Path] = []
        self.link_pairs: list[tuple[Path, Path]] = []
        self.cleanup_paths: list[Path] = []

    def acquire_lock(self, path: Path) -> LockOutcome:
        return self._delegate.acquire_lock(path)

    def create_temp(self, directory: Path, prefix: str) -> TempOutcome:
        outcome = self._delegate.create_temp(directory, prefix)
        if isinstance(outcome, TempFileCreated):
            self.temp_paths.append(outcome.file.path)
        return outcome

    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.link_pairs.append((source, destination))
        return self._delegate.publish_link(source, destination)

    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome:
        self.cleanup_paths.append(file.path)
        return self._delegate.unlink_owned(file)


class LinkFailurePublicationOps(RecordingPublicationOps):
    @override
    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.link_pairs.append((source, destination))
        return FileOperationFailed()


class LockFailurePublicationOps(RecordingPublicationOps):
    @override
    def acquire_lock(self, path: Path) -> LockOutcome:
        del path
        return FileOperationFailed()


class ReplacementRacePublicationOps(RecordingPublicationOps):
    def __init__(self) -> None:
        super().__init__()
        self.replacement_temp: Path | None = None
        self.replacement_lock: Path | None = None

    @override
    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.link_pairs.append((source, destination))
        lock_path = destination.with_suffix(destination.suffix + ".lock")
        source.unlink()
        lock_path.unlink()
        _ = source.write_bytes(b"replacement-temp")
        _ = lock_path.write_bytes(b"replacement-lock")
        self.replacement_temp = source
        self.replacement_lock = lock_path
        return FileOperationFailed()


class FinalRacePublicationOps(RecordingPublicationOps):
    def __init__(self) -> None:
        super().__init__()
        self.raced_final: Path | None = None

    @override
    def acquire_lock(self, path: Path) -> LockOutcome:
        outcome = super().acquire_lock(path)
        if isinstance(outcome, LockAcquired) and self.raced_final is None:
            final_path = path.with_suffix("")
            _ = final_path.write_bytes(b"other-owner")
            self.raced_final = final_path
        return outcome


class LinkRacePublicationOps(RecordingPublicationOps):
    def __init__(self) -> None:
        super().__init__()
        self.raced_final: Path | None = None

    @override
    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.link_pairs.append((source, destination))
        if self.raced_final is None:
            outcome = self._delegate.publish_link(source, destination)
            assert isinstance(outcome, HardLinkPublished)
            self.raced_final = destination
            return CandidateUnavailable()
        return self._delegate.publish_link(source, destination)


class PostLinkCorruptionPublicationOps(RecordingPublicationOps):
    def __init__(self) -> None:
        super().__init__()
        self.corrupted_final: Path | None = None

    @override
    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.link_pairs.append((source, destination))
        outcome = self._delegate.publish_link(source, destination)
        if isinstance(outcome, HardLinkPublished):
            _ = destination.write_bytes(b"corrupted-after-link")
            self.corrupted_final = destination
        return outcome


class PostLinkReplacementPublicationOps(RecordingPublicationOps):
    def __init__(self, replacement_payload: bytes) -> None:
        super().__init__()
        self._replacement_payload: bytes = replacement_payload
        self.replaced_final: Path | None = None

    @override
    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        self.link_pairs.append((source, destination))
        outcome = self._delegate.publish_link(source, destination)
        if isinstance(outcome, HardLinkPublished):
            destination.unlink()
            _ = destination.write_bytes(self._replacement_payload)
            self.replaced_final = destination
        return outcome


class UnsafeTempPublicationOps(RecordingPublicationOps):
    def __init__(self, outside_path: Path) -> None:
        super().__init__()
        self._outside_path: Path = outside_path

    @override
    def create_temp(self, directory: Path, prefix: str) -> TempOutcome:
        del directory, prefix
        self._outside_path.touch(exist_ok=False)
        self.temp_paths.append(self._outside_path)
        status = self._outside_path.stat()
        return TempFileCreated(
            OwnedFile(
                path=self._outside_path,
                identity=FileIdentity(device=status.st_dev, inode=status.st_ino),
            )
        )


class CleanupFailurePublicationOps(RecordingPublicationOps):
    def __init__(self, *, fail_temp: bool, fail_lock: bool) -> None:
        super().__init__()
        self._fail_temp: bool = fail_temp
        self._fail_lock: bool = fail_lock

    @override
    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome:
        self.cleanup_paths.append(file.path)
        is_lock = file.path.name.endswith(".lock")
        if (is_lock and self._fail_lock) or (not is_lock and self._fail_temp):
            return CleanupFailed()
        return self._delegate.unlink_owned(file)


def capture_owned_file(path: Path) -> OwnedFile:
    status = path.lstat()
    return OwnedFile(
        path=path,
        identity=FileIdentity(device=status.st_dev, inode=status.st_ino),
    )


def install_move_other_owner_race(
    monkeypatch: pytest.MonkeyPatch,
    victim: Path,
    moved_payload: bytes,
) -> None:
    real_replace = os.replace

    def move_other_owner(source_path: Path, destination_path: Path) -> None:
        if source_path == victim:
            source_path.unlink()
            _ = source_path.write_bytes(moved_payload)
        real_replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", move_other_owner)
