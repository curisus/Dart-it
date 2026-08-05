import os

import pytest

from dart_crawler.dart_api import DartApi
from dart_crawler.http_client import HttpxClient


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("OPEN_DART_API_KEY"),
    reason="OPEN_DART_API_KEY is not set",
)
def test_live_samsung_disclosure_search() -> None:
    api_key = os.environ["OPEN_DART_API_KEY"]
    with HttpxClient() as client:
        result = DartApi(client, api_key=api_key).list_disclosures(
            "00126380",
            "A001",
        )
    assert result.ok is True
    assert result.data is not None
    assert result.data
