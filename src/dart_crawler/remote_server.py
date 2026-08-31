"""MCP streamable-http server returning report data with no local filesystem."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Final, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import SecretStr, StrictStr, TypeAdapter, ValidationError
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from dart_crawler.crawler_service import CrawlerService
from dart_crawler.excel_contract_errors import excel_failure
from dart_crawler.excel_cursor import cursor_secret_from_environment
from dart_crawler.excel_page_loader import execute_prepared_excel_page
from dart_crawler.excel_page_models import ExcelPage
from dart_crawler.excel_query_service import (
    CrawlerServiceFactory,
    ExcelQueryServiceFactory,
)
from dart_crawler.excel_request_validation import (
    bind_excel_cursor,
    validate_excel_request,
)
from dart_crawler.http_client import HttpClient, HttpxClient
from dart_crawler.json_rpc_guard import JsonRpcRequestGuard
from dart_crawler.query_limits import REMOTE_QUERY_LIMITS
from dart_crawler.remote_excel_tool import register_remote_excel_tool
from dart_crawler.result import (
    ErrorCode,
    ErrorInfo,
    JsonValue,
    Result,
    error_info,
)
from dart_crawler.tool_catalog import register_query_tools

_API_KEY_HEADER: Final = "x-opendart-api-key"
_AUTHORIZATION_HEADER: Final = "authorization"
_BEARER_SCHEME: Final = "bearer"
_API_KEY_QUERY_PARAM: Final = "key"
_MISSING_KEY_NEXT_ACTION: Final = (
    "X-OpenDART-API-Key 헤더(또는 Authorization: Bearer, "
    "또는 URL의 ?key= 값)에 OpenDART API 키를 설정한 뒤 다시 호출하세요."
)

T = TypeVar("T")
_QUERY_PARAMS_ADAPTER: Final[TypeAdapter[Mapping[str, str]]] = TypeAdapter(
    Mapping[str, str]
)
_SCOPE_STRING_ADAPTER: Final[TypeAdapter[str]] = TypeAdapter(StrictStr)


def create_remote_server() -> MCPServer:
    """Register shared queries and the remote-only JSON page loader.

    The export group is deliberately absent: a remote request has no writable
    filesystem to receive a file, so this surface returns data only.
    """
    mcp = MCPServer("dart_crawler", version="0.1.0")
    register_query_tools(mcp, _with_remote_service)
    register_remote_excel_tool(mcp, _load_remote_excel_page)
    return mcp


def build_app(
    *,
    path: str = "/api/mcp",
    server: MCPServer | None = None,
) -> Starlette:
    """Build the ASGI application that serves the remote tools."""
    active_server = create_remote_server() if server is None else server
    app = active_server.streamable_http_app(
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
    app.add_middleware(JsonRpcRequestGuard, path=path)
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
        self._app: ASGIApp = app
        self._path: str = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            method = _scope_string(scope, "method")
            request_path = _scope_string(scope, "path")
            if (
                method is not None
                and request_path == self._path
                and method != "POST"
            ):
                refusal = Response(status_code=405, headers={"Allow": "POST"})
                await refusal(scope, receive, send)
                return
        await self._app(scope, receive, send)


def _with_remote_service(
    ctx: Context,
    operation: Callable[[CrawlerService], Result[T]],
    /,
) -> Result[T]:
    api_key = _api_key_from_request(ctx)
    if not api_key.ok or api_key.data is None:
        return Result[T].failure(
            api_key.error if api_key.error is not None else _missing_key_error(),
            next_action=api_key.next_action,
        )
    with HttpxClient() as http_client:
        return operation(
            CrawlerService(
                api_key.data,
                http_client,
                limits=REMOTE_QUERY_LIMITS,
            )
        )


def _load_remote_excel_page(
    raw_request: JsonValue,
    ctx: Context,
) -> Result[ExcelPage]:
    validated_result = validate_excel_request(raw_request)
    validated = validated_result.data
    if validated is None:
        return _as_excel_page_failure(validated_result)
    secret_result = cursor_secret_from_environment()
    secret = secret_result.data
    if secret is None:
        return _as_excel_page_failure(secret_result)
    prepared_result = bind_excel_cursor(validated, cursor_secret=secret)
    prepared = prepared_result.data
    if prepared is None:
        return _as_excel_page_failure(prepared_result)
    api_key_result = _api_key_from_request(ctx)
    api_key = api_key_result.data
    if api_key is None:
        return _as_excel_page_failure(api_key_result)
    with HttpxClient() as http_client:
        return execute_prepared_excel_page(
            prepared,
            cursor_secret=secret,
            factory=_excel_page_factory(api_key, http_client),
        )


def _excel_page_factory(
    api_key: SecretStr,
    http_client: HttpClient,
) -> ExcelQueryServiceFactory:
    return CrawlerServiceFactory(api_key, http_client)


def _as_excel_page_failure[SourceT](
    result: Result[SourceT],
) -> Result[ExcelPage]:
    if result.error is None:
        return excel_failure("invalid_request")
    return Result[ExcelPage].failure(
        result.error,
        warnings=result.warnings,
        next_action=result.next_action,
    )


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
        return Result[SecretStr].success(SecretStr(query_key))
    return _missing_key()


def _query_parameter(ctx: Context, name: str) -> str:
    try:
        request = ctx.request_context.request
    except ValueError:
        # A Context built with no request_context at all. On the shared path
        # ctx.headers raises this first, so the guard only protects direct
        # calls; stdio reaches the getattr below with request=None instead.
        return ""
    raw_params = getattr(request, "query_params", None)
    try:
        params = _QUERY_PARAMS_ADAPTER.validate_python(raw_params)
    except ValidationError:
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
    direct = next(_nonblank_header_values(headers, _API_KEY_HEADER), "")
    if direct:
        return Result[SecretStr].success(SecretStr(direct))
    for authorization in _nonblank_header_values(headers, _AUTHORIZATION_HEADER):
        components = authorization.split(maxsplit=1)
        if len(components) != 2:
            continue
        scheme, credentials = components
        if scheme.casefold() == _BEARER_SCHEME and credentials:
            return Result[SecretStr].success(SecretStr(credentials))
    return _missing_key()


def _nonblank_header_values(
    headers: Mapping[str, str],
    name: str,
) -> Iterator[str]:
    for key, value in headers.items():
        if key.casefold() == name:
            normalized = value.strip()
            if normalized:
                yield normalized


def _scope_string(scope: Scope, key: str) -> str | None:
    try:
        return _SCOPE_STRING_ADAPTER.validate_python(scope.get(key))
    except ValidationError:
        return None


def _missing_key() -> Result[SecretStr]:
    return Result[SecretStr].failure(
        _missing_key_error(),
        next_action=_MISSING_KEY_NEXT_ACTION,
    )


def _missing_key_error() -> ErrorInfo:
    return error_info(
        ErrorCode.CONFIG_ERROR,
        "요청에 OpenDART API 키가 없습니다.",
        retryable=False,
    )
