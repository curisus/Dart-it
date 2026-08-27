from dataclasses import dataclass
from typing import Final

import anyio
import httpx2
import pytest
from mcp_types import CallToolResult, TextContent
from pydantic import SecretStr, TypeAdapter

from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpClient
from dart_crawler.query_limits import QueryLimits
from dart_crawler.remote_server import build_app
from dart_crawler.result import JsonObject, JsonValue, Result

RCEPT_NO = "20260515001658"
ATTACHMENT_ID = f"opendart:{RCEPT_NO}:audit.xml"
MCP_PATH = "/api/mcp"
MCP_ACCEPT = "application/json, text/event-stream"
JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


@dataclass(frozen=True, slots=True)
class RemoteRequest:
    path: str = MCP_PATH
    headers: tuple[tuple[str, str], ...] = ()


_DEFAULT_REMOTE_REQUEST: Final = RemoteRequest()


def listed_attachment() -> Attachment:
    return Attachment(
        attachment_id=ATTACHMENT_ID,
        rcept_no=RCEPT_NO,
        source_rcept_no=RCEPT_NO,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )


async def post_jsonrpc(
    method: str,
    params: JsonObject,
    target: RemoteRequest = _DEFAULT_REMOTE_REQUEST,
) -> JsonObject:
    app = build_app()
    request: JsonObject = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.post(
            target.path,
            json=request,
            headers={"Accept": MCP_ACCEPT, **dict(target.headers)},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = JSON_OBJECT_ADAPTER.validate_json(response.content)
    return JSON_OBJECT_ADAPTER.validate_python(payload["result"])


async def request(method: str, path: str) -> httpx2.Response:
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        with anyio.fail_after(10):
            return await client.request(
                method,
                path,
                headers={"Accept": MCP_ACCEPT},
            )


def install_key_recording_service(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, QueryLimits]]:
    captured: list[tuple[str, QueryLimits]] = []

    class RecordingService:
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
            assert rcept_no == RCEPT_NO
            return Result.success((listed_attachment(),))

    monkeypatch.setattr("dart_crawler.remote_server.CrawlerService", RecordingService)
    return captured


async def call_tool_envelope(
    name: str,
    arguments: JsonObject,
    target: RemoteRequest = _DEFAULT_REMOTE_REQUEST,
) -> JsonObject:
    called = CallToolResult.model_validate(
        await post_jsonrpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            target,
        )
    )
    content = called.content[0]
    assert isinstance(content, TextContent)
    return JSON_OBJECT_ADAPTER.validate_json(content.text)


def json_object(value: JsonValue) -> JsonObject:
    return JSON_OBJECT_ADAPTER.validate_python(value)
