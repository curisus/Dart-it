"""Process-wide cache of the parsed OpenDART company directory.

The directory (corpCode.xml, about 120,000 companies) is public data and the
same for every API key, so one parsed copy serves every request of a process
for COMPANY_DIRECTORY_TTL_SECONDS. This is the only state the server keeps
between requests; the key that downloaded the directory is never retained.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

from defusedxml import ElementTree

from dart_crawler.company_name_matching import (
    CompanyCode,
    _name_readings,
    _NameReadings,
)
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.zip_safety import ArchiveLimits, inspect_archive, read_member

COMPANY_DIRECTORY_TTL_SECONDS: Final[float] = 3600

type Clock = Callable[[], float]


class CompanyDirectorySource(Protocol):
    """OpenDART capability required to load the company directory."""

    def download_company_codes(self) -> Result[bytes]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CompanyDirectoryIndex:
    """Immutable parsed directory with the readings company ranking reuses.

    entries keeps the archive order; readings[i] belongs to entries[i].
    """

    entries: tuple[CompanyCode, ...]
    readings: tuple[_NameReadings, ...]
    by_corp_code: Mapping[str, CompanyCode]

    def find(self, corp_code: str) -> CompanyCode | None:
        """Return the company registered under one corp_code, if any."""
        return self.by_corp_code.get(corp_code)


def build_company_directory_index(
    entries: tuple[CompanyCode, ...],
) -> CompanyDirectoryIndex:
    """Index parsed entries and precompute every name reading once."""
    by_corp_code: dict[str, CompanyCode] = {}
    for entry in entries:
        by_corp_code.setdefault(entry.corp_code, entry)
    return CompanyDirectoryIndex(
        entries=entries,
        readings=tuple(_name_readings(entry.company_name) for entry in entries),
        by_corp_code=MappingProxyType(by_corp_code),
    )


@dataclass(frozen=True, slots=True)
class _CachedDirectory:
    index: CompanyDirectoryIndex
    loaded_at: float


class _DirectoryCache:
    """One directory per process; concurrent first loads download once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached: _CachedDirectory | None = None

    def load(
        self,
        source: CompanyDirectorySource,
        clock: Clock,
    ) -> Result[CompanyDirectoryIndex]:
        # The lock is held through the download so that callers arriving
        # during a load wait for it instead of starting their own.
        with self._lock:
            cached = self._cached
            if (
                cached is not None
                and clock() - cached.loaded_at < COMPANY_DIRECTORY_TTL_SECONDS
            ):
                return Result.success(cached.index)
            loaded = _download_directory(source)
            if loaded.ok and loaded.data is not None:
                self._cached = _CachedDirectory(loaded.data, clock())
            return loaded

    def clear(self) -> None:
        with self._lock:
            self._cached = None


_CACHE: Final = _DirectoryCache()


def load_company_directory(
    source: CompanyDirectorySource,
    *,
    clock: Clock = time.monotonic,
) -> Result[CompanyDirectoryIndex]:
    """Return the cached directory, downloading it when absent or expired.

    Failures are returned to the caller and never cached.
    """
    return _CACHE.load(source, clock)


def clear_company_directory_cache() -> None:
    """Forget the cached directory (tests start from an empty cache)."""
    _CACHE.clear()


def _download_directory(
    source: CompanyDirectorySource,
) -> Result[CompanyDirectoryIndex]:
    archive = source.download_company_codes()
    if not archive.ok or archive.data is None:
        return Result.failure(
            archive.error
            if archive.error is not None
            else error_info(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "회사코드 목록을 수집할 수 없습니다.",
                retryable=True,
            ),
            next_action="잠시 후 회사 검색을 다시 시도하세요.",
        )
    parsed_archive = _parse_company_archive(archive.data)
    if not parsed_archive.ok or parsed_archive.data is None:
        return Result.failure(
            parsed_archive.error
            if parsed_archive.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED,
                "회사코드 목록을 해석할 수 없습니다.",
                retryable=False,
            ),
            next_action="OpenDART 회사코드 파일 형식을 확인하세요.",
        )
    return Result.success(build_company_directory_index(parsed_archive.data))


def _parse_company_archive(content: bytes) -> Result[tuple[CompanyCode, ...]]:
    inspection = inspect_archive(content, limits=ArchiveLimits())
    if not inspection.ok or inspection.data is None:
        return Result.failure(
            inspection.error
            if inspection.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED,
                "회사코드 ZIP이 잘못되었습니다.",
                retryable=False,
            )
        )
    xml_name = next(
        (
            member.name
            for member in inspection.data
            if member.name.casefold().endswith("corpcode.xml")
        ),
        None,
    )
    if xml_name is None:
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "CORPCODE.xml을 찾지 못했습니다.",
                retryable=False,
            )
        )
    xml_result = read_member(content, xml_name, limits=ArchiveLimits())
    if not xml_result.ok or xml_result.data is None:
        return Result.failure(
            xml_result.error
            if xml_result.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED,
                "CORPCODE.xml을 읽지 못했습니다.",
                retryable=False,
            )
        )
    try:
        root = ElementTree.fromstring(xml_result.data)
    except ElementTree.ParseError:
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "CORPCODE.xml 형식이 잘못되었습니다.",
                retryable=False,
            )
        )
    entries: list[CompanyCode] = []
    for item in root.findall("./list"):
        corp_code = item.findtext("corp_code", "")
        company_name = item.findtext("corp_name", "").strip()
        stock_code = item.findtext("stock_code", "").strip() or None
        if len(corp_code) != 8 or not corp_code.isdigit() or not company_name:
            continue
        entries.append(CompanyCode(corp_code, company_name, stock_code))
    return Result.success(tuple(entries))
