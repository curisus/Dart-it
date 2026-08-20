from collections.abc import Mapping
from typing import Any

import anyio
import httpx2
import pytest
from mcp_types import CallToolResult, ListToolsResult
from pydantic import SecretStr

from dart_crawler.api_models import DartListRow
from dart_crawler.attachments import AttachmentService
from dart_crawler.crawler_service import PARSER_VERSION, CrawlerService, LoadedDocument
from dart_crawler.dart_api import DartApi
from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
    SourceCoverage,
)
from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpResponse
from dart_crawler.mcp_server import mcp as local_mcp
from dart_crawler.remote_server import (
    _api_key_from_headers,
    build_app,
    create_remote_server,
)
from dart_crawler.result import ErrorCode, JsonObject, Result, WarningCode

_RCEPT_NO = "20260515001658"
_ATTACHMENT_ID = f"opendart:{_RCEPT_NO}:audit.xml"
_MCP_PATH = "/api/mcp"
_MCP_ACCEPT = "application/json, text/event-stream"

_OPINION = "<heading>독립된 감사인의 감사보고서</heading><p>적정의견을 표명합니다.</p>"
_BALANCE_SHEET = (
    "<heading>재무상태표</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>자산총계</td><td>1,000</td></tr></table>"
)
_INCOME = (
    "<heading>손익계산서</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>매출액</td><td>500</td></tr></table>"
)
_EQUITY = (
    "<heading>자본변동표</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>자본총계</td><td>800</td></tr></table>"
)
_CASH_FLOW = (
    "<heading>현금흐름표</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>현금및현금성자산</td><td>200</td></tr></table>"
)


def _report_xml(*, with_cash_flow: bool = True) -> bytes:
    sections = (_OPINION, _BALANCE_SHEET, _INCOME, _EQUITY) + (
        (_CASH_FLOW,) if with_cash_flow else ()
    )
    return f"<document>{''.join(sections)}</document>".encode()


class _NoopHttpClient:
    """HTTP client that fails the test if the service reaches the network."""

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        raise AssertionError((url, params))

    def close(self) -> None:
        return None


def _listed_attachment() -> Attachment:
    return Attachment(
        attachment_id=_ATTACHMENT_ID,
        rcept_no=_RCEPT_NO,
        source_rcept_no=_RCEPT_NO,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )


def _forbid_disclosure(_self: DartApi, rcept_no: str) -> Result[DartListRow]:
    raise AssertionError(rcept_no)


def _service_reading(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> CrawlerService:
    """Build a service whose attachment listing and read are fully local."""

    def list_attachments(
        _self: AttachmentService,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        assert rcept_no == _RCEPT_NO
        return Result.success((_listed_attachment(),))

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        assert rcept_no == _RCEPT_NO
        assert selection == _listed_attachment()
        return Result.success(content)

    monkeypatch.setattr(DartApi, "find_disclosure", _forbid_disclosure)
    monkeypatch.setattr(AttachmentService, "list", list_attachments)
    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)
    return CrawlerService(SecretStr("test-key"), _NoopHttpClient())


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
async def test_remote_server_exposes_exactly_the_eleven_data_tools() -> None:
    listed = await create_remote_server().list_tools()

    names = {tool.name for tool in listed}
    assert names == {
        "search_companies",
        "list_report_filings",
        "list_report_attachments",
        "list_report_sections",
        "get_report_sections",
        "get_financial_statements",
        "get_major_accounts",
        "get_financial_indicators",
        "get_report_topics",
        "get_company_profile",
        "get_ownership_reports",
    }
    assert "export_report_excel" not in names


@pytest.mark.anyio
async def test_local_surface_is_the_remote_surface_plus_the_export_group() -> None:
    """The catalog is the single source of coverage for both surfaces."""
    remote = {tool.name: tool for tool in await create_remote_server().list_tools()}
    local = {tool.name: tool for tool in await local_mcp.list_tools()}

    assert set(local) == set(remote) | {
        "export_report_excel",
        "export_report_markdown",
    }
    # Every shared tool must be byte-identical on both surfaces: same
    # description, same advertised parameters. A divergence means a tool was
    # defined outside the catalog.
    for name, remote_tool in remote.items():
        assert local[name].description == remote_tool.description
        assert local[name].input_schema == remote_tool.input_schema


async def _post_jsonrpc(
    method: str,
    params: JsonObject,
    *,
    path: str = _MCP_PATH,
    headers: Mapping[str, str] | None = None,
) -> JsonObject:
    """Call the built ASGI app in process, without an initialize handshake."""
    app = build_app()
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.post(
            path,
            json=request,
            headers={"Accept": _MCP_ACCEPT, **(headers or {})},
        )
    assert response.status_code == 200
    # json_response=True means one JSON body, not an event stream.
    assert response.headers["content-type"].startswith("application/json")
    payload: object = response.json()
    assert isinstance(payload, dict)
    result: object = payload["result"]
    assert isinstance(result, dict)
    return result


async def _request(method: str, path: str) -> httpx2.Response:
    """Send one bare request to the built app, bounded so a hang fails fast."""
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        # Without the deadline a regression would block this test forever
        # instead of reporting the defect it is meant to catch.
        with anyio.fail_after(10):
            return await client.request(method, path, headers={"Accept": _MCP_ACCEPT})


@pytest.mark.anyio
async def test_get_on_the_mcp_path_is_refused_instead_of_opening_a_stream() -> None:
    """A GET must not park a serverless function on an idle SSE stream."""
    response = await _request("GET", _MCP_PATH)

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["DELETE", "OPTIONS", "PUT", "HEAD"])
async def test_every_other_method_on_the_mcp_path_advertises_post_only(
    method: str,
) -> None:
    """The SDK's own 405 advertises GET, which is the method that hangs."""
    response = await _request(method, _MCP_PATH)

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.anyio
async def test_the_method_guard_leaves_other_paths_to_the_router() -> None:
    """Only the MCP endpoint is POST-only; the guard is not a blanket filter."""
    response = await _request("GET", "/not-the-mcp-path")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_tools_list_over_http_needs_no_api_key() -> None:
    """A client must be able to register the connector before holding a key."""
    listed = ListToolsResult.model_validate(await _post_jsonrpc("tools/list", {}))

    assert {tool.name for tool in listed.tools} == {
        "search_companies",
        "list_report_filings",
        "list_report_attachments",
        "list_report_sections",
        "get_report_sections",
        "get_financial_statements",
        "get_major_accounts",
        "get_financial_indicators",
        "get_report_topics",
        "get_company_profile",
        "get_ownership_reports",
    }
    selection_tool = next(
        tool for tool in listed.tools if tool.name == "get_report_sections"
    )
    # The injected Context must stay out of the advertised parameters.
    assert set(selection_tool.input_schema["properties"]) == {
        "rcept_no",
        "attachment_id",
        "section_ids",
        "section_kinds",
    }


@pytest.mark.anyio
async def test_tools_call_without_key_header_returns_config_error_envelope() -> None:
    """A keyless call must fail in the Result envelope, never as HTTP 401."""
    called = CallToolResult.model_validate(
        await _post_jsonrpc(
            "tools/call",
            {
                "name": "list_report_attachments",
                "arguments": {"rcept_no": _RCEPT_NO},
            },
        )
    )

    envelope = called.structured_content
    assert envelope is not None
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["code"] == "CONFIG_ERROR"
    assert envelope["error"]["retryable"] is False
    assert "X-OpenDART-API-Key" in envelope["next_action"]


def _install_key_recording_service(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Swap the service the remote tools build for one that records its key."""
    captured: list[str] = []

    class _RecordingService:
        def __init__(self, api_key: SecretStr, http_client: object) -> None:
            captured.append(api_key.get_secret_value())

        def list_report_attachments(
            self,
            rcept_no: str,
        ) -> Result[tuple[Attachment, ...]]:
            assert rcept_no == _RCEPT_NO
            return Result.success((_listed_attachment(),))

    monkeypatch.setattr("dart_crawler.remote_server.CrawlerService", _RecordingService)
    return captured


async def _call_attachments_tool(
    *,
    path: str = _MCP_PATH,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    called = CallToolResult.model_validate(
        await _post_jsonrpc(
            "tools/call",
            {
                "name": "list_report_attachments",
                "arguments": {"rcept_no": _RCEPT_NO},
            },
            path=path,
            headers=headers,
        )
    )
    envelope: dict[str, Any] | None = called.structured_content
    assert envelope is not None
    return envelope


@pytest.mark.anyio
async def test_query_key_lets_a_headerless_client_call_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """claude.ai connectors without the header beta send the key in the URL."""
    captured = _install_key_recording_service(monkeypatch)

    envelope = await _call_attachments_tool(path=f"{_MCP_PATH}?key=query-key")

    assert envelope["ok"] is True
    assert captured == ["query-key"]


@pytest.mark.anyio
async def test_header_key_wins_over_the_query_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_key_recording_service(monkeypatch)

    envelope = await _call_attachments_tool(
        path=f"{_MCP_PATH}?key=query-key",
        headers={"X-OpenDART-API-Key": "direct-key"},
    )

    assert envelope["ok"] is True
    assert captured == ["direct-key"]


@pytest.mark.anyio
async def test_blank_query_key_still_fails_with_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The recording service keeps a regression here from reaching the real
    # DART servers: a blank key that slipped through would call the network.
    _install_key_recording_service(monkeypatch)

    envelope = await _call_attachments_tool(path=f"{_MCP_PATH}?key=%20%20")

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "CONFIG_ERROR"
    assert "?key=" in envelope["next_action"]


def test_list_report_sections_summarizes_every_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_reading(monkeypatch, _report_xml())

    result = service.list_report_sections(_RCEPT_NO, _ATTACHMENT_ID)

    assert result.ok is True
    assert result.data is not None
    listing = result.data
    assert listing.rcept_no == _RCEPT_NO
    assert listing.attachment_id == _ATTACHMENT_ID
    assert listing.report_title == "독립된 감사인의 감사보고서"
    assert listing.source_type == "xml"
    assert len(listing.source_sha256) == 64
    assert listing.parser_version == PARSER_VERSION
    assert listing.coverage_complete is True
    assert listing.section_count == 5
    assert [section.section_id for section in listing.sections] == [
        "s001-opinion",
        "s002-balance_sheet",
        "s003-income",
        "s004-equity",
        "s005-cash_flow",
    ]
    assert listing.total_cell_count == sum(
        section.cell_count for section in listing.sections
    )
    assert listing.total_cell_count == 16
    assert listing.total_text_char_count == sum(
        section.text_char_count for section in listing.sections
    )
    # 제목 5개(14+5+5+5+5) + 감사의견 문단 12자, 표 셀은 제외된다.
    assert listing.total_text_char_count == 46
    assert result.warnings == ()


def test_get_report_sections_returns_only_the_selected_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_reading(monkeypatch, _report_xml())

    result = service.get_report_sections(
        _RCEPT_NO,
        _ATTACHMENT_ID,
        section_ids=("s001-opinion",),
        section_kinds=("cash_flow",),
    )

    assert result.ok is True
    assert result.data is not None
    selected = result.data
    assert [section.section_id for section in selected.sections] == [
        "s001-opinion",
        "s005-cash_flow",
    ]
    assert selected.parser_version == PARSER_VERSION
    assert selected.returned_cell_count == 4
    # 감사의견 제목 14자 + 문단 12자 + 현금흐름표 제목 5자, 표 셀은 제외된다.
    assert selected.returned_text_char_count == 31
    cash_flow_table = selected.sections[1].blocks[1].table
    assert cash_flow_table is not None
    assert cash_flow_table.rows == (
        ("계정", "당기"),
        ("현금및현금성자산", "200"),
    )
    assert result.warnings == ()


def test_get_report_sections_rejects_a_selection_that_matches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_reading(monkeypatch, _report_xml())

    result = service.get_report_sections(
        _RCEPT_NO,
        _ATTACHMENT_ID,
        section_ids=("s099-note",),
    )

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_missing_core_statement_warns_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_reading(monkeypatch, _report_xml(with_cash_flow=False))

    listing = service.list_report_sections(_RCEPT_NO, _ATTACHMENT_ID)
    selection = service.get_report_sections(
        _RCEPT_NO,
        _ATTACHMENT_ID,
        section_kinds=("statements",),
    )

    assert listing.ok is True
    assert selection.ok is True
    for result in (listing, selection):
        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert warning.code is WarningCode.PARTIAL_COLLECTION
        assert warning.details["missing_sections"] == ["현금흐름표"]


def test_section_tools_refuse_data_that_failed_document_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parsing-fidelity failure must never surface as returned cells."""
    malformed = ParsedDocument(
        sections=(
            DocumentSection(
                title="재무상태표",
                kind=SectionKind.BALANCE_SHEET,
                blocks=(
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=(("계정", "당기"), ("자산총계",)),
                    ),
                ),
            ),
        ),
        source_sha256="c" * 64,
        source_type="xml",
        # Coverage is deliberately complete so the gate can only trip on the
        # ragged table, not on an earlier coverage check.
        source_coverage=SourceCoverage(
            source_text_token_count=0,
            captured_text_token_count=0,
            source_text_sha256="d" * 64,
            captured_text_sha256="d" * 64,
            source_table_count=1,
            captured_table_count=1,
            source_cell_count=3,
            captured_cell_count=3,
            source_image_count=0,
            captured_image_count=0,
        ),
    )

    def load_malformed(
        _self: CrawlerService,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[LoadedDocument]:
        assert rcept_no == _RCEPT_NO
        assert attachment_id == _ATTACHMENT_ID
        return Result.success(
            LoadedDocument(
                document=malformed,
                attachment_title="별도감사보고서",
                source_rcept_no=_RCEPT_NO,
            )
        )

    monkeypatch.setattr(CrawlerService, "_load_parsed_document", load_malformed)
    service = CrawlerService(SecretStr("test-key"), _NoopHttpClient())

    listing = service.list_report_sections(_RCEPT_NO, _ATTACHMENT_ID)
    selection = service.get_report_sections(
        _RCEPT_NO,
        _ATTACHMENT_ID,
        section_kinds=("statements",),
    )

    for result in (listing, selection):
        assert result.ok is False
        assert result.data is None
        assert result.error is not None
        assert result.error.code is ErrorCode.VALIDATION_FAILED
