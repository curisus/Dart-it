from __future__ import annotations

import os
import stat
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class OwnedFile:
    path: Path
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class LockAcquired:
    file: OwnedFile


@dataclass(frozen=True, slots=True)
class CandidateUnavailable:
    pass


@dataclass(frozen=True, slots=True)
class FileOperationFailed:
    pass


type LockOutcome = LockAcquired | CandidateUnavailable | FileOperationFailed


@dataclass(frozen=True, slots=True)
class TempFileCreated:
    file: OwnedFile


type TempOutcome = TempFileCreated | FileOperationFailed


@dataclass(frozen=True, slots=True)
class HardLinkPublished:
    file: OwnedFile


type LinkOutcome = (
    HardLinkPublished | CandidateUnavailable | FileOperationFailed
)


@dataclass(frozen=True, slots=True)
class CleanupCompleted:
    pass


@dataclass(frozen=True, slots=True)
class CleanupFailed:
    pass


type CleanupOutcome = CleanupCompleted | CleanupFailed


class ExcelPublicationFileOps(Protocol):
    def acquire_lock(self, path: Path) -> LockOutcome: ...

    def create_temp(self, directory: Path, prefix: str) -> TempOutcome: ...

    def publish_link(self, source: Path, destination: Path) -> LinkOutcome: ...

    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome: ...


@dataclass(frozen=True, slots=True)
class SystemExcelPublicationFileOps:
    def acquire_lock(self, path: Path) -> LockOutcome:
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            return CandidateUnavailable()
        except OSError:
            return FileOperationFailed()
        owned = _capture_owned_file(path, descriptor)
        if owned is None:
            with suppress(OSError):
                os.close(descriptor)
            return FileOperationFailed()
        try:
            os.close(descriptor)
        except OSError:
            _ = _unlink_matching_file(owned)
            return FileOperationFailed()
        return LockAcquired(owned)

    def create_temp(self, directory: Path, prefix: str) -> TempOutcome:
        try:
            descriptor, raw_path = tempfile.mkstemp(
                dir=directory,
                prefix=prefix,
                suffix=".xlsx",
            )
        except OSError:
            return FileOperationFailed()
        path = Path(raw_path)
        owned = _capture_owned_file(path, descriptor)
        if owned is None:
            with suppress(OSError):
                os.close(descriptor)
            return FileOperationFailed()
        try:
            os.close(descriptor)
        except OSError:
            _ = _unlink_matching_file(owned)
            return FileOperationFailed()
        return TempFileCreated(owned)

    def publish_link(self, source: Path, destination: Path) -> LinkOutcome:
        try:
            descriptor = os.open(source, os.O_RDONLY)
        except OSError:
            return FileOperationFailed()
        opened = _capture_owned_file(source, descriptor)
        if opened is None or not is_current_regular_file(opened):
            with suppress(OSError):
                os.close(descriptor)
            return FileOperationFailed()
        published_file: OwnedFile | None = None
        try:
            os.link(source, destination)
        except FileExistsError:
            outcome: LinkOutcome = CandidateUnavailable()
        except OSError:
            outcome = FileOperationFailed()
        else:
            published = _capture_regular_path(destination)
            current_source = _capture_regular_path(source)
            if published is None:
                outcome = FileOperationFailed()
            elif (
                published.identity == opened.identity
                and current_source == opened
            ):
                published_file = published
                outcome = HardLinkPublished(file=published)
            else:
                _unlink_published_if_source_link(
                    published,
                    opened,
                    current_source,
                )
                outcome = FileOperationFailed()
        try:
            os.close(descriptor)
        except OSError:
            if published_file is not None:
                _ = _unlink_matching_file(published_file)
            return FileOperationFailed()
        return outcome

    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome:
        return _unlink_matching_file(file)


SYSTEM_EXCEL_PUBLICATION_FILE_OPS: Final[ExcelPublicationFileOps] = (
    SystemExcelPublicationFileOps()
)


def publish_owned_link(
    file_ops: ExcelPublicationFileOps,
    source: OwnedFile,
    destination: Path,
) -> LinkOutcome:
    if not is_current_regular_file(source):
        return FileOperationFailed()
    outcome = file_ops.publish_link(source.path, destination)
    if not isinstance(outcome, HardLinkPublished):
        return outcome
    if outcome.file.identity != source.identity:
        _ = file_ops.unlink_owned(outcome.file)
        return FileOperationFailed()
    return outcome


def _capture_owned_file(path: Path, descriptor: int) -> OwnedFile | None:
    try:
        status = os.fstat(descriptor)
    except OSError:
        return None
    if not _is_regular_non_reparse(status):
        return None
    return OwnedFile(
        path=path,
        identity=_identity(status),
    )


def _capture_regular_path(path: Path) -> OwnedFile | None:
    try:
        status = os.lstat(path)
    except OSError:
        return None
    if not _is_regular_non_reparse(status):
        return None
    return OwnedFile(path=path, identity=_identity(status))


def _unlink_published_if_source_link(
    published: OwnedFile,
    opened: OwnedFile,
    current_source: OwnedFile | None,
) -> None:
    tied_to_source = published.identity == opened.identity or (
        current_source is not None
        and published.identity == current_source.identity
    )
    if tied_to_source:
        _ = _unlink_matching_file(published)


def is_current_regular_file(file: OwnedFile) -> bool:
    current = _capture_regular_path(file.path)
    return current is not None and current.identity == file.identity


def _identity(status: os.stat_result) -> FileIdentity:
    return FileIdentity(device=status.st_dev, inode=status.st_ino)


def _is_regular_non_reparse(status: os.stat_result) -> bool:
    if not stat.S_ISREG(status.st_mode):
        return False
    if sys.platform != "win32":
        return True
    return not bool(
        status.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _unlink_matching_file(file: OwnedFile) -> CleanupOutcome:
    try:
        status = os.lstat(file.path)
    except FileNotFoundError:
        return CleanupCompleted()
    except OSError:
        return CleanupFailed()
    current = _identity(status)
    if current != file.identity:
        return CleanupCompleted()
    try:
        file.path.unlink()
    except FileNotFoundError:
        return CleanupCompleted()
    except OSError:
        return CleanupFailed()
    return CleanupCompleted()
