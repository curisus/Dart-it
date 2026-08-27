from collections.abc import Mapping

import pytest

from dart_crawler.query_limits import REMOTE_QUERY_LIMITS
from dart_crawler.remote_server import _api_key_from_headers
from dart_crawler.result import ErrorCode
from tests.remote_server_test_support import (
    MCP_PATH,
    RCEPT_NO,
    RemoteRequest,
    call_tool_envelope,
    install_key_recording_service,
    json_object,
)


def test_direct_api_key_header_is_accepted() -> None:
    result = _api_key_from_headers({"X-OpenDART-API-Key": "direct-key"})

    assert result.ok is True
    assert result.data is not None
    assert result.data.get_secret_value() == "direct-key"


def test_api_key_header_lookup_ignores_case_and_surrounding_whitespace() -> None:
    result = _api_key_from_headers({"x-opendart-api-key": "  spaced-key  "})

    assert result.ok is True
    assert result.data is not None
    assert result.data.get_secret_value() == "spaced-key"


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_bearer_authorization_is_accepted_as_fallback(scheme: str) -> None:
    result = _api_key_from_headers({"Authorization": f"{scheme} bearer-key"})

    assert result.ok is True
    assert result.data is not None
    assert result.data.get_secret_value() == "bearer-key"


def test_direct_header_is_preferred_over_bearer_authorization() -> None:
    result = _api_key_from_headers(
        {
            "X-OpenDART-API-Key": "direct-key",
            "Authorization": "Bearer bearer-key",
        }
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.get_secret_value() == "direct-key"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(None, id="stdio-transport-has-no-headers"),
        pytest.param({}, id="no-headers-at-all"),
        pytest.param({"X-OpenDART-API-Key": "   "}, id="blank-direct-header"),
        pytest.param({"Authorization": "Bearer   "}, id="blank-bearer-credentials"),
        pytest.param({"Authorization": "Basic direct-key"}, id="unsupported-scheme"),
        pytest.param({"Authorization": "direct-key"}, id="scheme-less-authorization"),
    ],
)
def test_missing_api_key_fails_with_config_error(
    headers: Mapping[str, str] | None,
) -> None:
    result = _api_key_from_headers(headers)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.CONFIG_ERROR
    assert result.error.retryable is False
    assert "X-OpenDART-API-Key" in (result.next_action or "")


@pytest.mark.anyio
async def test_query_key_lets_a_headerless_client_call_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = install_key_recording_service(monkeypatch)
    target = RemoteRequest(path=f"{MCP_PATH}?key=query-key")

    envelope = await call_tool_envelope(
        "list_report_attachments",
        {"rcept_no": RCEPT_NO},
        target,
    )

    assert envelope["ok"] is True
    assert captured == [("query-key", REMOTE_QUERY_LIMITS)]


@pytest.mark.anyio
async def test_header_key_wins_over_the_query_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = install_key_recording_service(monkeypatch)
    target = RemoteRequest(
        path=f"{MCP_PATH}?key=query-key",
        headers=(("X-OpenDART-API-Key", "direct-key"),),
    )

    envelope = await call_tool_envelope(
        "list_report_attachments",
        {"rcept_no": RCEPT_NO},
        target,
    )

    assert envelope["ok"] is True
    assert captured == [("direct-key", REMOTE_QUERY_LIMITS)]


@pytest.mark.anyio
async def test_blank_query_key_still_fails_with_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_key_recording_service(monkeypatch)
    target = RemoteRequest(path=f"{MCP_PATH}?key=%20%20")

    envelope = await call_tool_envelope(
        "list_report_attachments",
        {"rcept_no": RCEPT_NO},
        target,
    )
    error = json_object(envelope["error"])
    next_action = envelope["next_action"]

    assert envelope["ok"] is False
    assert error["code"] == "CONFIG_ERROR"
    assert isinstance(next_action, str)
    assert "?key=" in next_action
