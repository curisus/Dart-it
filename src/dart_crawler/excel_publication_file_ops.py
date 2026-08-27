from __future__ import annotations

import os
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
    pass


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
            os.link(source, destination)
        except FileExistsError:
            return CandidateUnavailable()
        except OSError:
            return FileOperationFailed()
        return HardLinkPublished()

    def unlink_owned(self, file: OwnedFile) -> CleanupOutcome:
        return _unlink_matching_file(file)


SYSTEM_EXCEL_PUBLICATION_FILE_OPS: Final[ExcelPublicationFileOps] = (
    SystemExcelPublicationFileOps()
)


def _capture_owned_file(path: Path, descriptor: int) -> OwnedFile | None:
    try:
        status = os.fstat(descriptor)
    except OSError:
        return None
    return OwnedFile(
        path=path,
        identity=FileIdentity(device=status.st_dev, inode=status.st_ino),
    )


def _unlink_matching_file(file: OwnedFile) -> CleanupOutcome:
    try:
        status = os.lstat(file.path)
    except FileNotFoundError:
        return CleanupCompleted()
    except OSError:
        return CleanupFailed()
    current = FileIdentity(device=status.st_dev, inode=status.st_ino)
    if current != file.identity:
        return CleanupCompleted()
    try:
        file.path.unlink()
    except FileNotFoundError:
        return CleanupCompleted()
    except OSError:
        return CleanupFailed()
    return CleanupCompleted()
