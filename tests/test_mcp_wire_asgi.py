import json
from typing import Final

import httpx2
import pytest
from mcp.server import MCPServer
from mcp_types import CallToolResult

from dart_crawler.excel_page_models import (
    EXCEL_PAGE_BUDGET_BYTES,
    ExcelDataDomain,
    ExcelPage,
)
from dart_crawler.mcp_wire import (
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    WIRE_REQUEST_ID,
    WireProfile,
    excel_result_to_call_tool_result,
    measure_excel_result_wire,
)
from dart_crawler.remote_server import build_app
from dart_crawler.result import Result

_MCP_PATH: Final = "/api/mcp"
_PROTOCOL_KEY: Final = "io.modelcontextprotocol/protocolVersion"
_CAPABILITIES_KEY: Final = "io.modelcontextprotocol/clientCapabilities"


def _page_result(value: str = '한글 "quoted"\nline') -> Result[ExcelPage]:
    return Result.success(
        ExcelPage(
            domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
            request_fingerprint="a" * 64,
            source_fingerprint="b" * 64,
            columns=("value",),
            rows=({"value": value},),
            total_rows=1,
            offset=0,
            page_size=1,
            returned_rows=1,
        )
    )


def _probe_server(result: Result[ExcelPage], calls: list[int]) -> MCPServer:
    server = MCPServer(MCP_SERVER_NAME, version=MCP_SERVER_VERSION)

    @server.tool(name="wire_probe")
    def wire_probe() -> CallToolResult:
        calls.append(1)
        return excel_result_to_call_tool_result(result)

    return server


def _legacy_request() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": WIRE_REQUEST_ID,
            "method": "tools/call",
            "params": {"name": "wire_probe", "arguments": {}},
        },
        separators=(",", ":"),
    ).encode()


def _modern_request() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": WIRE_REQUEST_ID,
            "method": "tools/call",
            "params": {
                "name": "wire_probe",
                "arguments": {},
                "_meta": {
                    _PROTOCOL_KEY: WireProfile.MODERN.value,
                    _CAPABILITIES_KEY: {},
                },
            },
        },
        separators=(",", ":"),
    ).encode()


@pytest.mark.anyio
async def test_actual_asgi_tool_call_lengths_equal_oracle_for_both_profiles() -> None:
    # Given: a controlled fake source explicitly returning the mapped CallToolResult.
    result = _page_result()
    calls: list[int] = []
    app = build_app(server=_probe_server(result, calls))
    report = measure_excel_result_wire(result)
    expected = {
        measurement.profile: measurement.byte_length
        for measurement in report.measurements
    }

    # When: legacy and 2026-07-28 requests drive the actual in-process ASGI surface.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        legacy = await client.post(
            _MCP_PATH,
            content=_legacy_request(),
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        calls_after_legacy = len(calls)
        modern = await client.post(
            _MCP_PATH,
            content=_modern_request(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": WireProfile.MODERN.value,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "wire_probe",
            },
        )

    # Then: each body is the exact oracle size and executes the fake source once.
    assert legacy.status_code == 200
    assert modern.status_code == 200
    assert legacy.headers["content-type"] == "application/json"
    assert modern.headers["content-type"] == "application/json"
    assert len(legacy.content) == expected[WireProfile.LEGACY]
    assert len(modern.content) == expected[WireProfile.MODERN]
    assert calls_after_legacy == 1
    assert len(calls) == 2


@pytest.mark.anyio
async def test_http_200_cannot_replace_the_completed_wire_budget_check() -> None:
    # Given: a fake tool whose duplicated completed body exceeds the page budget.
    result = _page_result("x" * 1_800_000)
    calls: list[int] = []
    app = build_app(server=_probe_server(result, calls))
    report = measure_excel_result_wire(result)

    # When: the fake tool returns an otherwise successful legacy HTTP response.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.post(
            _MCP_PATH,
            content=_legacy_request(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    # Then: only the exact byte oracle detects rejection despite the 200 status.
    expected = next(
        measurement.byte_length
        for measurement in report.measurements
        if measurement.profile is WireProfile.LEGACY
    )
    assert response.status_code == 200
    assert len(response.content) == expected
    assert report.fits_strictly(EXCEL_PAGE_BUDGET_BYTES) is False
    assert len(response.content) >= EXCEL_PAGE_BUDGET_BYTES
    assert len(calls) == 1
