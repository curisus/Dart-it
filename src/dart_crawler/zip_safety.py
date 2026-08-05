"""Bounded ZIP inspection that rejects path traversal and oversized archives."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath
from zipfile import BadZipFile, ZipFile

from dart_crawler.result import ErrorCode, Result, error_info


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Maximum archive dimensions accepted by the collector."""

    max_files: int = 10_000
    max_compressed_bytes: int = 100 * 1024 * 1024
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_entry_bytes: int = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """Safe metadata for one non-directory ZIP member."""

    name: str
    compressed_bytes: int
    uncompressed_bytes: int


def inspect_archive(
    content: bytes,
    *,
    limits: ArchiveLimits,
) -> Result[tuple[ArchiveMember, ...]]:
    """Validate ZIP structure, size limits, and member paths."""
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_files:
                return _invalid_archive("압축파일의 문서 수가 제한을 초과했습니다.")
            members: list[ArchiveMember] = []
            compressed_total = 0
            uncompressed_total = 0
            for info in infos:
                safe_name = _safe_member_name(info.filename)
                if safe_name is None:
                    return _invalid_archive(
                        "압축파일에 안전하지 않은 경로가 포함되어 있습니다."
                    )
                if info.is_dir():
                    continue
                if info.file_size > limits.max_entry_bytes:
                    return _invalid_archive(
                        "압축파일 내부 문서가 크기 제한을 초과했습니다."
                    )
                compressed_total += info.compress_size
                uncompressed_total += info.file_size
                if compressed_total > limits.max_compressed_bytes:
                    return _invalid_archive("압축파일 크기가 제한을 초과했습니다.")
                if uncompressed_total > limits.max_uncompressed_bytes:
                    return _invalid_archive("압축 해제 크기가 제한을 초과했습니다.")
                members.append(
                    ArchiveMember(
                        name=safe_name,
                        compressed_bytes=info.compress_size,
                        uncompressed_bytes=info.file_size,
                    )
                )
            return Result.success(tuple(members))
    except (BadZipFile, OSError, ValueError):
        return _invalid_archive("압축파일 형식을 해석할 수 없습니다.")


def read_member(
    content: bytes,
    member_name: str,
    *,
    limits: ArchiveLimits,
) -> Result[bytes]:
    """Read one validated ZIP member without extracting to disk."""
    inspection = inspect_archive(content, limits=limits)
    if not inspection.ok or inspection.data is None:
        return Result.failure(
            inspection.error
            if inspection.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED,
                "압축파일을 검증할 수 없습니다.",
                retryable=False,
            )
        )
    safe_target = _safe_member_name(member_name)
    if safe_target is None or safe_target not in {
        item.name for item in inspection.data
    }:
        return Result.failure(
            error_info(
                ErrorCode.NOT_FOUND,
                "압축파일에서 요청한 문서를 찾을 수 없습니다.",
                retryable=False,
            )
        )
    try:
        with ZipFile(BytesIO(content)) as archive:
            return Result.success(archive.read(safe_target))
    except (BadZipFile, KeyError, OSError, RuntimeError):
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "압축파일 내부 문서를 읽을 수 없습니다.",
                retryable=False,
            )
        )


def _safe_member_name(name: str) -> str | None:
    posix_name = PurePosixPath(name.replace("\\", "/"))
    windows_name = PureWindowsPath(name)
    if (
        posix_name.is_absolute()
        or windows_name.is_absolute()
        or bool(windows_name.drive)
        or ".." in posix_name.parts
        or ".." in windows_name.parts
    ):
        return None
    return str(posix_name)


def _invalid_archive(message: str) -> Result[tuple[ArchiveMember, ...]]:
    return Result.failure(error_info(ErrorCode.PARSE_FAILED, message, retryable=False))
