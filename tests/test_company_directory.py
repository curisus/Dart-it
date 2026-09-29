import gc
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields

import pytest

from dart_crawler.company_directory import (
    COMPANY_DIRECTORY_TTL_SECONDS,
    CompanyDirectoryIndex,
    load_company_directory,
)
from dart_crawler.company_name_matching import CompanyCode, _name_readings
from dart_crawler.result import ErrorCode, Result, error_info
from tests.company_directory_fixtures import directory_archive

_ENTRIES = (
    CompanyCode("00126380", "Sample Holdings", "005930"),
    CompanyCode("00126381", "SK 바이오", None),
    CompanyCode("00126382", "Other Company", None),
)
_ARCHIVE = directory_archive(_ENTRIES)
_FAKE_KEY = "FAKEKEY0123456789abcdef0123456789abcdef0"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class CountingSource:
    archives: list[Result[bytes]]
    api_key: str = _FAKE_KEY
    downloads: int = 0

    def download_company_codes(self) -> Result[bytes]:
        self.downloads += 1
        if len(self.archives) > 1:
            return self.archives.pop(0)
        return self.archives[0]


def _succeeding() -> CountingSource:
    return CountingSource([Result.success(_ARCHIVE)])


def test_index_keeps_archive_order_and_precomputed_readings() -> None:
    result = load_company_directory(_succeeding())

    assert result.ok is True
    assert result.data is not None
    assert result.data.entries == _ENTRIES
    assert result.data.readings == tuple(
        _name_readings(entry.company_name) for entry in _ENTRIES
    )
    assert result.data.find("00126381") == _ENTRIES[1]
    assert result.data.find("99999999") is None


def test_directory_is_reused_until_the_ttl_then_reloaded() -> None:
    # Given
    clock = FakeClock()
    source = _succeeding()
    first = load_company_directory(source, clock=clock)

    # When: just before the hour the cached index answers
    clock.now += COMPANY_DIRECTORY_TTL_SECONDS - 0.001
    cached = load_company_directory(source, clock=clock)

    # Then
    assert source.downloads == 1
    assert cached.data is first.data

    # When: at the hour the directory is downloaded again
    clock.now += 0.001
    reloaded = load_company_directory(source, clock=clock)

    # Then
    assert source.downloads == 2
    assert reloaded.ok is True
    assert reloaded.data is not first.data


def test_concurrent_first_loads_download_once() -> None:
    # Given
    workers = 8
    barrier = threading.Barrier(workers)
    downloading = threading.Event()
    release = threading.Event()

    class SlowSource:
        def __init__(self) -> None:
            self.downloads = 0

        def download_company_codes(self) -> Result[bytes]:
            self.downloads += 1
            downloading.set()
            # Keep the load in flight while the other callers arrive.
            release.wait(timeout=5)
            return Result.success(_ARCHIVE)

    source = SlowSource()

    def load() -> Result[CompanyDirectoryIndex]:
        barrier.wait(timeout=5)
        return load_company_directory(source)

    # When
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(load) for _ in range(workers)]
        assert downloading.wait(timeout=5)
        release.set()
        results = [future.result(timeout=10) for future in futures]

    # Then
    assert source.downloads == 1
    assert all(result.ok for result in results)
    assert len({id(result.data) for result in results}) == 1


def test_failed_download_is_not_cached_and_keeps_its_envelope() -> None:
    # Given
    failure = Result[bytes].failure(
        error_info(ErrorCode.UPSTREAM_RATE_LIMIT, "호출 한도 초과", retryable=True),
        next_action="원래 안내",
    )
    source = CountingSource([failure, Result.success(_ARCHIVE)])

    # When
    failed = load_company_directory(source)
    recovered = load_company_directory(source)

    # Then
    assert failed.ok is False
    assert failed.error == failure.error
    assert failed.next_action == "잠시 후 회사 검색을 다시 시도하세요."
    assert failed.warnings == ()
    assert recovered.ok is True
    assert source.downloads == 2


def test_unparsable_archive_is_not_cached() -> None:
    # Given
    source = CountingSource([Result.success(b"not a zip"), Result.success(_ARCHIVE)])

    # When
    failed = load_company_directory(source)
    recovered = load_company_directory(source)

    # Then
    assert failed.ok is False
    assert failed.error is not None
    assert failed.error.code is ErrorCode.PARSE_FAILED
    assert failed.next_action == "OpenDART 회사코드 파일 형식을 확인하세요."
    assert recovered.ok is True
    assert source.downloads == 2


def test_cached_directory_keeps_no_reference_to_the_source_or_key() -> None:
    # Given
    source = _succeeding()
    source_ref = weakref.ref(source)

    # When
    result = load_company_directory(source)
    del source
    gc.collect()

    # Then
    assert source_ref() is None
    assert result.data is not None
    stored = [
        getattr(item, column.name)
        for items in (result.data.entries, result.data.readings)
        for item in items
        for column in fields(item)
    ]
    assert all(_FAKE_KEY not in str(value) for value in stored)
    assert _FAKE_KEY not in repr(result.data)


@pytest.mark.parametrize("corp_code", ["", " 00126380", "0012638"])
def test_find_requires_the_exact_corp_code(corp_code: str) -> None:
    result = load_company_directory(_succeeding())

    assert result.data is not None
    assert result.data.find(corp_code) is None
