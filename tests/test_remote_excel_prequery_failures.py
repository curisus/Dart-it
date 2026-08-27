import base64
import hashlib
import hmac
import json

import pytest
from pydantic import SecretBytes, SecretStr

from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_cursor import (
    CursorSecret,
    ExcelCursorPayload,
    encode_excel_cursor,
)
from dart_crawler.excel_dataset_identity import normalized_request_fingerprint
from dart_crawler.excel_page_models import ExcelDataDomain, ExcelPage
from dart_crawler.excel_query_service import ExcelQueryServiceFactory
from dart_crawler.http_client import HttpClient
from dart_crawler.result import ErrorCode, JsonObject, JsonValue, Result
from tests.excel_dispatch_fakes import RecordingExcelServiceFactory
from tests.excel_service_fixture_factory import empty_excel_service_responses
from tests.remote_server_test_support import (
    RemoteRequest,
    call_tool_envelope,
)

_ACTIVE_TEXT = "a" * 32
_ROTATED_TEXT = "b" * 32
_ACTIVE_SECRET = CursorSecret(value=SecretBytes(_ACTIVE_TEXT.encode()))
_FINGERPRINT = normalized_request_fingerprint(
    ExcelDataDomain.SEARCH_COMPANIES,
    SearchCompaniesArguments(company_query="회사"),
)


def _request(*, cursor: str | None = None, page_size: int = 1_000) -> JsonObject:
    return {
        "domain": "search_companies",
        "arguments": {"company_query": "회사"},
        "page_size": page_size,
        "cursor": cursor,
    }


def _arguments_with_unknown_field() -> JsonObject:
    return {"company_query": "회사", "unknown": 1}


async def _call(
    request: JsonValue,
    *,
    authenticated: bool,
) -> Result[ExcelPage]:
    headers = (("X-OpenDART-API-Key", "request-key"),) if authenticated else ()
    envelope = await call_tool_envelope(
        "load_excel_page",
        {"request": request},
        RemoteRequest(headers=headers),
    )
    return Result[ExcelPage].model_validate(envelope)


def _install_factory_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    builds: list[str] = []
    factory = RecordingExcelServiceFactory(empty_excel_service_responses())

    def build_factory(
        api_key: SecretStr,
        http_client: HttpClient,
    ) -> ExcelQueryServiceFactory:
        del http_client
        builds.append(api_key.get_secret_value())
        return factory

    monkeypatch.setattr(
        "dart_crawler.remote_server._excel_page_factory",
        build_factory,
    )
    return builds


def _cursor(
    *,
    request_fingerprint: str = _FINGERPRINT,
    page_size: int = 1_000,
    secret: CursorSecret = _ACTIVE_SECRET,
) -> str:
    return encode_excel_cursor(
        ExcelCursorPayload(
            request_fingerprint=request_fingerprint,
            source_fingerprint="c" * 64,
            offset=1,
            page_index=1,
            page_size=page_size,
        ),
        secret=secret,
    )


def _schema_mismatch_cursor() -> str:
    payload: JsonObject = {
        "offset": 1,
        "page_index": 1,
        "page_size": 1_000,
        "request_fingerprint": _FINGERPRINT,
        "schema_version": 2,
        "source_fingerprint": "c" * 64,
        "version": 1,
    }
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(
        _ACTIVE_SECRET.value.get_secret_value(),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    return f"{_base64url(payload_bytes)}.{_base64url(signature)}"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _assert_reason(result: Result[ExcelPage], reason: str) -> None:
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is False
    assert result.error.details == {"reason": reason}
    assert result.warnings == ()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_request", "reason"),
    [
        pytest.param(None, "invalid_request", id="null-request"),
        pytest.param([], "invalid_request", id="array-request"),
        pytest.param("request", "invalid_request", id="string-request"),
        pytest.param(7, "invalid_request", id="integer-request"),
        pytest.param(True, "invalid_request", id="boolean-request"),
        pytest.param(
            {**_request(), "unknown": "field"},
            "invalid_request",
            id="unknown-request-field",
        ),
        pytest.param(
            {**_request(), "arguments": []},
            "invalid_request",
            id="array-arguments",
        ),
        pytest.param(
            {**_request(), "arguments": "arguments"},
            "invalid_request",
            id="string-arguments",
        ),
        pytest.param(
            {**_request(), "arguments": True},
            "invalid_request",
            id="boolean-arguments",
        ),
        pytest.param(
            {
                **_request(),
                "arguments": _arguments_with_unknown_field(),
            },
            "invalid_request",
            id="unknown-argument-field",
        ),
        pytest.param(
            {**_request(), "page_size": 1_000.0},
            "invalid_request",
            id="float-page-size",
        ),
        pytest.param(
            {**_request(), "page_size": "1000"},
            "invalid_request",
            id="string-page-size",
        ),
        pytest.param(
            {**_request(), "cursor": 7},
            "invalid_request",
            id="integer-cursor",
        ),
        pytest.param(
            {**_request(cursor="bad"), "page_size": True},
            "invalid_request",
            id="request-before-cursor",
        ),
        pytest.param(_request(cursor="bad"), "invalid_cursor", id="cursor-before-auth"),
        pytest.param(
            _request(cursor=_cursor(request_fingerprint="d" * 64)),
            "cursor_request_mismatch",
            id="request-binding",
        ),
        pytest.param(
            _request(cursor=_cursor(), page_size=999),
            "cursor_page_size_mismatch",
            id="page-size-binding",
        ),
        pytest.param(
            _request(cursor=_schema_mismatch_cursor()),
            "cursor_schema_mismatch",
            id="schema-binding",
        ),
    ],
)
async def test_prequery_request_and_cursor_failures_precede_auth(
    monkeypatch: pytest.MonkeyPatch,
    raw_request: JsonValue,
    reason: str,
) -> None:
    # Given: no API key and a request that fails before authentication.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", _ACTIVE_TEXT)
    builds = _install_factory_counter(monkeypatch)

    # When: the actual remote tool processes the request.
    result = await _call(raw_request, authenticated=False)

    # Then: the exact earlier-stage reason wins with no factory or source call.
    _assert_reason(result, reason)
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert builds == []


@pytest.mark.anyio
async def test_missing_or_rotated_configuration_never_reaches_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one valid request and one cursor signed before secret rotation.
    builds = _install_factory_counter(monkeypatch)
    monkeypatch.delenv("DART_MCP_CURSOR_SECRET", raising=False)

    # When: configuration is absent, then replaced by a different valid secret.
    missing = await _call(_request(), authenticated=True)
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", _ROTATED_TEXT)
    rotated = await _call(_request(cursor=_cursor()), authenticated=True)

    # Then: configuration is typed, rotation is invalid_cursor, and calls stay zero.
    _assert_reason(missing, "invalid_request")
    assert missing.error is not None
    assert missing.error.code is ErrorCode.CONFIG_ERROR
    _assert_reason(rotated, "invalid_cursor")
    assert builds == []


@pytest.mark.anyio
async def test_missing_key_after_valid_request_uses_existing_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a fully valid first-page request and cursor configuration.
    monkeypatch.setenv("DART_MCP_CURSOR_SECRET", _ACTIVE_TEXT)
    builds = _install_factory_counter(monkeypatch)

    # When: the actual call omits every API-key channel.
    result = await _call(_request(), authenticated=False)

    # Then: the existing CONFIG_ERROR remains unchanged and no source is built.
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.CONFIG_ERROR
    assert result.error.details == {}
    assert builds == []
