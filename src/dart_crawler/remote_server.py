"""MCP streamable-http server returning report data with no local filesystem."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from dart_crawler.crawler_service import CrawlerService
from dart_crawler.domain import Attachment, Company, Filing
from dart_crawler.http_client import HttpxClient
from dart_crawler.result import ErrorCode, ErrorInfo, Result, error_info
from dart_crawler.section_models import ReportSectionData, ReportSectionList

_API_KEY_HEADER: Final = "x-opendart-api-key"
_AUTHORIZATION_HEADER: Final = "authorization"
_BEARER_SCHEME: Final = "bearer"
_API_KEY_QUERY_PARAM: Final = "key"
_MISSING_KEY_NEXT_ACTION: Final = (
    "X-OpenDART-API-Key 헤더(또는 Authorization: Bearer, "
    "또는 URL의 ?key= 값)에 OpenDART API 키를 설정한 뒤 다시 호출하세요."
)

T = TypeVar("T")


def create_remote_server() -> MCPServer:
    """Register the five read-only tools served over streamable HTTP.

    The Excel export is deliberately absent: a remote request has no writable
    filesystem to receive a workbook, so this surface returns data only.
    """
    mcp = MCPServer("dart_crawler", version="0.1.0")

    @mcp.tool()
    def search_companies(
        company_query: str,
        report_kind: str,
        ctx: Context,
    ) -> Result[tuple[Company, ...]]:
        """Search up to five companies with the requested report family."""
        return _with_remote_service(
            ctx,
            lambda service: service.search_companies(company_query, report_kind),
        )

    @mcp.tool()
    def list_report_filings(
        corp_code: str,
        report_kind: str,
        ctx: Context,
    ) -> Result[tuple[Filing, ...]]:
        """List recent five-year representative filings."""
        return _with_remote_service(
            ctx,
            lambda service: service.list_report_filings(corp_code, report_kind),
        )

    @mcp.tool()
    def list_report_attachments(
        rcept_no: str,
        ctx: Context,
    ) -> Result[tuple[Attachment, ...]]:
        """List selectable separate and consolidated report attachments."""
        return _with_remote_service(
            ctx,
            lambda service: service.list_report_attachments(rcept_no),
        )

    @mcp.tool()
    def list_report_sections(
        rcept_no: str,
        attachment_id: str,
        ctx: Context,
    ) -> Result[ReportSectionList]:
        """List one attachment's sections as a table of contents.

        Each entry carries the section_id, title, kind, and cell count needed to
        choose what to request from get_report_sections, without returning any
        of the section content.
        """
        return _with_remote_service(
            ctx,
            lambda service: service.list_report_sections(rcept_no, attachment_id),
        )

    @mcp.tool()
    def get_report_sections(
        rcept_no: str,
        attachment_id: str,
        ctx: Context,
        section_ids: tuple[str, ...] = (),
        section_kinds: tuple[str, ...] = (),
    ) -> Result[ReportSectionData]:
        """Return the full content of the selected sections of one attachment.

        Select by section_ids from list_report_sections, by section_kinds, or by
        both: the union is returned in source order. section_kinds accepts a
        section kind such as balance_sheet or note, plus the alias "statements"
        for the four core financial statements. At least one selector is
        required, and a selection larger than the response limit is rejected
        rather than truncated.
        """
        return _with_remote_service(
            ctx,
            lambda service: service.get_report_sections(
                rcept_no,
                attachment_id,
                section_ids,
                section_kinds,
            ),
        )

    return mcp


def build_app(*, path: str = "/api/mcp") -> Starlette:
    """Build the ASGI application that serves the remote tools."""
    app = create_remote_server().streamable_http_app(
        streamable_http_path=path,
        json_response=True,
        stateless_http=True,
        # Omitting transport_security makes the SDK auto-enable DNS rebinding
        # protection with a localhost-only Host allowlist, which answers every
        # request reaching a deployed domain with HTTP 421. Authentication here
        # is the per-request API key header, not the Host header.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    app.add_middleware(_PostOnlyEndpoint, path=path)
    return app


class _PostOnlyEndpoint:
    """Answer every non-POST request to the MCP path with 405 immediately.

    This transport pairs ``json_response`` with ``stateless_http``: each POST
    carries its own reply and no session outlives it, so there is never
    anything for the server to push on a server-to-client stream. The SDK
    nonetheless answers GET by opening an SSE stream and holding it until the
    client disconnects, which on a serverless host lets one unauthenticated GET
    pin a function for its entire maximum duration. Refusing here also replaces
    the SDK's ``Allow: GET, POST, DELETE``, which names GET as usable.
    """

    def __init__(self, app: ASGIApp, *, path: str) -> None:
        self._app = app
        self._path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            method: str = scope["method"]
            request_path: str = scope["path"]
            if request_path == self._path and method != "POST":
                refusal = Response(status_code=405, headers={"Allow": "POST"})
                await refusal(scope, receive, send)
                return
        await self._app(scope, receive, send)


def _with_remote_service(
    ctx: Context,
    operation: Callable[[CrawlerService], Result[T]],
) -> Result[T]:
    api_key = _api_key_from_request(ctx)
    if not api_key.ok or api_key.data is None:
        return Result.failure(
            api_key.error if api_key.error is not None else _missing_key_error(),
            next_action=api_key.next_action,
        )
    with HttpxClient() as http_client:
        return operation(CrawlerService(api_key.data, http_client))


def _api_key_from_request(ctx: Context) -> Result[SecretStr]:
    """Read the caller's OpenDART key from the headers, then the URL query.

    Headers stay the primary channel: a key inside the URL can end up in
    server access logs. The ``?key=`` fallback exists for MCP clients that
    cannot attach request headers at all — claude.ai custom connectors on
    accounts without the request-header beta send only the configured URL.
    """
    from_headers = _api_key_from_headers(ctx.headers)
    if from_headers.ok:
        return from_headers
    query_key = _query_parameter(ctx, _API_KEY_QUERY_PARAM)
    if query_key:
        return Result.success(SecretStr(query_key))
    return _missing_key()


def _query_parameter(ctx: Context, name: str) -> str:
    try:
        request = ctx.request_context.request
    except ValueError:
        # A Context built with no request_context at all. On the shared path
        # ctx.headers raises this first, so the guard only protects direct
        # calls; stdio reaches the getattr below with request=None instead.
        return ""
    params = getattr(request, "query_params", None)
    if not isinstance(params, Mapping):
        return ""
    value = params.get(name)
    return value.strip() if isinstance(value, str) else ""


def _api_key_from_headers(headers: Mapping[str, str] | None) -> Result[SecretStr]:
    """Read the caller's OpenDART key from the headers of one request.

    A missing key fails inside the Result envelope rather than as HTTP 401,
    because a 401 sends MCP clients into OAuth discovery. ``initialize`` and
    ``tools/list`` stay reachable without a key so a client can still register.
    """
    if headers is None:
        return _missing_key()
    direct = _header_value(headers, _API_KEY_HEADER)
    if direct:
        return Result.success(SecretStr(direct))
    scheme, _, credentials = _header_value(headers, _AUTHORIZATION_HEADER).partition(
        " "
    )
    bearer_key = credentials.strip()
    if scheme.casefold() == _BEARER_SCHEME and bearer_key:
        return Result.success(SecretStr(bearer_key))
    return _missing_key()


def _header_value(headers: Mapping[str, str], name: str) -> str:
    # Starlette's Headers mapping already matches case-insensitively, but a
    # plain dict does not, so the comparison happens here for both.
    for key, value in headers.items():
        if key.casefold() == name:
            return value.strip()
    return ""


def _missing_key() -> Result[SecretStr]:
    return Result.failure(
        _missing_key_error(),
        next_action=_MISSING_KEY_NEXT_ACTION,
    )


def _missing_key_error() -> ErrorInfo:
    return error_info(
        ErrorCode.CONFIG_ERROR,
        "요청에 OpenDART API 키가 없습니다.",
        retryable=False,
    )
