from dataclasses import dataclass
from typing import Final

import httpx2
import pytest
from pydantic import SecretStr, TypeAdapter

from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpClient
from dart_crawler.query_limits import REMOTE_QUERY_LIMITS, QueryLimits
from dart_crawler.remote_server import build_app
from dart_crawler.result import JsonObject, Result

_MCP_PATH: Final = "/api/mcp"
_MCP_ACCEPT: Final = "application/json, text/event-stream"
_JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)


@dataclass(frozen=True, slots=True)
class _AuthScenario:
    header_pairs: tuple[tuple[str, str], ...]
    query: str
    expected_key: str


async def _request(
    method: str,
    path: str,
    *,
    headers: httpx2.Headers,
    content: bytes | None = None,
) -> httpx2.Response:
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        return await client.request(
            method,
            path,
            headers=headers,
            content=content,
        )


def _json_headers(
    header_pairs: tuple[tuple[str, str], ...] = (),
) -> httpx2.Headers:
    return httpx2.Headers(
        (
            ("Accept", _MCP_ACCEPT),
            ("Content-Type", "application/json"),
            *header_pairs,
        )
    )


def _install_recording_service(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, QueryLimits]]:
    captured: list[tuple[str, QueryLimits]] = []

    class _RecordingService:
        def __init__(
            self,
            api_key: SecretStr,
            http_client: HttpClient,
            *,
            limits: QueryLimits,
        ) -> None:
            del http_client
            captured.append((api_key.get_secret_value(), limits))

        def list_report_attachments(
            self,
            rcept_no: str,
        ) -> Result[tuple[Attachment, ...]]:
            assert rcept_no == "20260515001658"
            return Result.success(())

    monkeypatch.setattr("dart_crawler.remote_server.CrawlerService", _RecordingService)
    return captured


@pytest.mark.anyio
async def test_post_keeps_single_json_response_when_request_is_json() -> None:
    # Given: a parseable JSON-RPC tools/list request.
    request = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

    # When: the real in-process ASGI endpoint receives the POST.
    response = await _request(
        "POST",
        _MCP_PATH,
        headers=_json_headers(),
        content=request,
    )

    # Then: transport remains a single JSON response.
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = _JSON_OBJECT_ADAPTER.validate_json(response.content)
    assert "result" in payload


@pytest.mark.anyio
async def test_get_keeps_405_and_advertises_post_only() -> None:
    # Given: the streamable HTTP MCP endpoint.
    headers = httpx2.Headers({"Accept": _MCP_ACCEPT})

    # When: a caller attempts GET.
    response = await _request("GET", _MCP_PATH, headers=headers)

    # Then: the endpoint refuses immediately and advertises POST only.
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            _AuthScenario(
                header_pairs=(
                    ("X-OpenDART-API-Key", " direct-first "),
                    ("X-OpenDART-API-Key", "direct-second"),
                    ("Authorization", "Bearer bearer-key"),
                ),
                query="?key=query-key",
                expected_key="direct-first",
            ),
            id="first-direct-header-wins",
        ),
        pytest.param(
            _AuthScenario(
                header_pairs=(
                    ("X-OpenDART-API-Key", "   "),
                    ("Authorization", "Bearer bearer-first"),
                    ("Authorization", "Bearer bearer-second"),
                ),
                query="?key=query-key",
                expected_key="bearer-first",
            ),
            id="blank-direct-falls-through-to-first-bearer",
        ),
        pytest.param(
            _AuthScenario(
                header_pairs=(
                    ("X-OpenDART-API-Key", "   "),
                    ("X-OpenDART-API-Key", "direct-after-blank"),
                    ("Authorization", "Bearer bearer-key"),
                ),
                query="?key=query-key",
                expected_key="direct-after-blank",
            ),
            id="first-nonblank-direct-duplicate-wins",
        ),
        pytest.param(
            _AuthScenario(
                header_pairs=(
                    ("Authorization", "Basic malformed"),
                    ("Authorization", "Bearer bearer-after-malformed"),
                ),
                query="?key=query-key",
                expected_key="bearer-after-malformed",
            ),
            id="first-well-formed-bearer-duplicate-wins",
        ),
        pytest.param(
            _AuthScenario(
                header_pairs=(("Authorization", "Basic malformed"),),
                query="?key=old-key&key=%20query-last%20",
                expected_key="query-last",
            ),
            id="malformed-bearer-falls-through-to-last-decoded-query-key",
        ),
    ],
)
async def test_authentication_precedence_is_request_scoped(
    monkeypatch: pytest.MonkeyPatch,
    scenario: _AuthScenario,
) -> None:
    # Given: distinct credentials at each supported precedence level.
    captured = _install_recording_service(monkeypatch)
    request = (
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
        b'{"name":"list_report_attachments","arguments":'
        b'{"rcept_no":"20260515001658"}}}'
    )

    # When: the actual ASGI tool-call path resolves authentication.
    response = await _request(
        "POST",
        f"{_MCP_PATH}{scenario.query}",
        headers=_json_headers(scenario.header_pairs),
        content=request,
    )

    # Then: the selected credential and normal request policy are exact.
    assert response.status_code == 200
    assert captured == [(scenario.expected_key, REMOTE_QUERY_LIMITS)]


def test_normal_remote_response_caps_are_characterized() -> None:
    # Given: the existing normal remote request policy.
    limits = REMOTE_QUERY_LIMITS

    # When/Then: its three ordinary-query response caps remain exact.
    assert limits.max_response_rows == 1_000
    assert limits.max_response_cells == 20_000
    assert limits.max_response_text_chars == 200_000
