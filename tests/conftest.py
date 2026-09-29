from collections.abc import Iterator

import pytest

from dart_crawler.company_directory import clear_company_directory_cache


@pytest.fixture(autouse=True)
def _empty_company_directory_cache() -> Iterator[None]:
    # The company directory is cached process-wide; every test starts without
    # one so a fake archive of one test never answers another.
    clear_company_directory_cache()
    yield
    clear_company_directory_cache()
