from pathlib import Path

import pytest

from dart_crawler.dart_api import DartApi
from dart_crawler.http_client import HttpxClient
from dart_crawler.settings import load_settings

_SETTINGS = load_settings(process_dir=Path(__file__).resolve().parents[1])


@pytest.mark.live
@pytest.mark.skipif(
    not _SETTINGS.ok,
    reason="OPEN_DART_API_KEY is not set in the environment or project .env",
)
def test_live_samsung_disclosure_search() -> None:
    settings = _SETTINGS.data
    assert settings is not None
    with HttpxClient() as client:
        result = DartApi(
            client,
            api_key=settings.api_key.get_secret_value(),
        ).list_disclosures(
            "00126380",
            "A001",
        )
    assert result.ok is True
    assert result.data is not None
    assert result.data
