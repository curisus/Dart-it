import json
from dataclasses import dataclass
from typing import Final

import httpx2
import pytest
from pydantic import SecretStr

from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpClient
from dart_crawler.query_limits import QueryLimits
from dart_crawler.remote_server import build_app
from dart_crawler.result import Result

_MCP_PATH: Final = "/api/mcp"
_MCP_HEADERS: Final = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "X-OpenDART-API-Key": "redacted-test-key",
}
_INVALID_BODY: Final = b'{"error":"invalid_json_rpc_request"}'


def _tool_call(id_json: bytes) -> bytes:
    return (
        b'{"jsonrpc":"2.0","id":'
        + id_json
        + b',"method":"tools/call","params":{"name":'
        b'"list_report_attachments","arguments":'
        b'{"rcept_no":"20260515001658"}}}'
    )


async def _post(content: bytes) -> httpx2.Response:
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        return await client.post(_MCP_PATH, headers=_MCP_HEADERS, content=content)


@dataclass(frozen=True, slots=True)
class _CallCounter:
    calls: list[str]


def _install_counting_service(
    monkeypatch: pytest.MonkeyPatch,
) -> _CallCounter:
    counter = _CallCounter(calls=[])

    class _CountingService:
        def __init__(
            self,
            api_key: SecretStr,
            http_client: HttpClient,
            *,
            limits: QueryLimits,
        ) -> None:
            del api_key, http_client, limits

        def list_report_attachments(
            self,
            rcept_no: str,
        ) -> Result[tuple[Attachment, ...]]:
            counter.calls.append(rcept_no)
            return Result.success(())

    monkeypatch.setattr("dart_crawler.remote_server.CrawlerService", _CountingService)
    return counter


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"{", id="malformed-json"),
        pytest.param(b"[]", id="batch"),
        pytest.param(b"null", id="top-level-null"),
        pytest.param(_tool_call(b"true"), id="boolean-id"),
        pytest.param(_tool_call(b"null"), id="null-id"),
        pytest.param(_tool_call(json.dumps("x" * 1_023).encode()), id="ascii-id-over"),
        pytest.param(_tool_call(json.dumps("가" * 171).encode()), id="unicode-id-over"),
        pytest.param(_tool_call(b"9" * 1_025), id="integer-id-over"),
        pytest.param(_tool_call(b"9" * 5_000), id="parser-limit-integer-id"),
        pytest.param(
            b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":NaN}',
            id="non-standard-nan",
        ),
        pytest.param(
            b'{"jsonrpc":"2.0","id":1,"id":2,"method":"tools/list"}',
            id="duplicate-top-level-key",
        ),
        pytest.param(
            b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
            b'{"name":"list_report_attachments","arguments":'
            b'{"rcept_no":"a","rcept_no":"b"}}}',
            id="duplicate-nested-key",
        ),
    ],
)
async def test_invalid_json_rpc_is_rejected_before_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    # Given: an adversarial JSON-RPC body and a tool-call counter.
    counter = _install_counting_service(monkeypatch)

    # When: the actual ASGI MCP endpoint receives the request.
    response = await _post(content)

    # Then: the guard returns the exact transport error without executing a tool.
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert response.content == _INVALID_BODY
    assert counter.calls == []


@pytest.mark.anyio
async def test_unpaired_surrogate_id_returns_transport_error_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a request ID containing an invalid unpaired UTF-16 surrogate.
    counter = _install_counting_service(monkeypatch)

    # When: the literal JSON escape reaches the actual in-process ASGI endpoint.
    response = await _post(_tool_call(b'"\\ud800"'))

    # Then: the boundary rejects it exactly without executing the requested tool.
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert response.content == _INVALID_BODY
    assert counter.calls == []


@pytest.mark.anyio
async def test_request_id_at_every_profile_boundary_is_accepted() -> None:
    # Given: an ASCII string whose independent JSON encoding is exactly 1024 bytes.
    request_id = "i" * 1_022
    assert len(json.dumps(request_id, separators=(",", ":")).encode()) == 1_024

    # When: the ID is used on a normal tools/list POST.
    response = await _post(
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": "tools/list"},
            separators=(",", ":"),
        ).encode()
    )

    # Then: the request reaches the SDK instead of the request guard.
    assert response.status_code == 200


@pytest.mark.anyio
async def test_missing_request_id_passes_to_sdk_notification_handling() -> None:
    # Given: a valid JSON-RPC notification with no id member.
    content = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'

    # When: the notification reaches the actual ASGI endpoint.
    response = await _post(content)

    # Then: the SDK handles it as a notification, not as a guard failure.
    assert response.status_code == 202
    assert response.content == b""
