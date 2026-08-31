import json
from typing import Final

import httpx2
from mcp_types import CallToolResult, TextContent
from pydantic import TypeAdapter

from dart_crawler.excel_page_models import ExcelPage
from dart_crawler.mcp_wire import (
    WIRE_REQUEST_ID,
    WireProfile,
    measure_excel_result_wire,
)
from dart_crawler.result import JsonObject, Result

MCP_PATH: Final = "/api/mcp"
_PROTOCOL_KEY: Final = "io.modelcontextprotocol/protocolVersion"
_CAPABILITIES_KEY: Final = "io.modelcontextprotocol/clientCapabilities"
_JSON_OBJECT: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)


def page_request_body(profile: WireProfile, request: JsonObject) -> bytes:
    params: JsonObject = {
        "name": "load_excel_page",
        "arguments": {"request": request},
    }
    if profile is WireProfile.MODERN:
        params["_meta"] = {
            _PROTOCOL_KEY: profile.value,
            _CAPABILITIES_KEY: {},
        }
    body: JsonObject = {
        "jsonrpc": "2.0",
        "id": WIRE_REQUEST_ID,
        "method": "tools/call",
        "params": params,
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def page_request_headers(profile: WireProfile) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-OpenDART-API-Key": "request-key",
    }
    if profile is WireProfile.MODERN:
        headers.update(
            {
                "MCP-Protocol-Version": profile.value,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "load_excel_page",
            }
        )
    return headers


def response_call_tool_result(response: httpx2.Response) -> CallToolResult:
    payload = _JSON_OBJECT.validate_json(response.content)
    result_value = _JSON_OBJECT.validate_python(payload["result"])
    return CallToolResult.model_validate(result_value)


def response_page_result(response: httpx2.Response) -> Result[ExcelPage]:
    called = response_call_tool_result(response)
    content = called.content[0]
    assert isinstance(content, TextContent)
    return Result[ExcelPage].model_validate_json(content.text)


def oracle_body(result: Result[ExcelPage], profile: WireProfile) -> bytes:
    report = measure_excel_result_wire(result)
    return next(
        measurement.body
        for measurement in report.measurements
        if measurement.profile is profile
    )
