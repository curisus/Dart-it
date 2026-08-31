from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, override

from pydantic import StrictBytes, StrictStr, TypeAdapter, ValidationError
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dart_crawler.result import JsonObject, JsonValue

INVALID_JSON_RPC_RESPONSE: Final = b'{"error":"invalid_json_rpc_request"}'
MAX_REQUEST_ID_BYTES: Final = 1_024
_JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
_BODY_ADAPTER: Final[TypeAdapter[bytes]] = TypeAdapter(StrictBytes)
_SCOPE_STRING_ADAPTER: Final[TypeAdapter[str]] = TypeAdapter(StrictStr)


@dataclass(frozen=True, slots=True)
class _DuplicateJsonKeyError(Exception):
    @override
    def __str__(self) -> str:
        return "duplicate JSON key"


class _NonStandardJsonNumberError(ValueError):
    pass


class _BodyReceive:
    def __init__(self, body: bytes) -> None:
        self._body: bytes = body
        self._sent: bool = False

    async def __call__(self) -> Message:
        if self._sent:
            return {"type": "http.disconnect"}
        self._sent = True
        return {"type": "http.request", "body": self._body, "more_body": False}


class JsonRpcRequestGuard:
    def __init__(self, app: ASGIApp, *, path: str) -> None:
        self._app: ASGIApp = app
        self._path: str = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        method = _scope_string(scope, "method")
        request_path = _scope_string(scope, "path")
        if method is None or request_path is None:
            await self._app(scope, receive, send)
            return
        if method != "POST" or request_path != self._path:
            await self._app(scope, receive, send)
            return
        body = await _read_body(receive)
        if body is None or not _is_valid_json_rpc_request(body):
            response = Response(
                content=INVALID_JSON_RPC_RESPONSE,
                status_code=400,
                headers={"Content-Type": "application/json"},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, _BodyReceive(body), send)


async def _read_body(receive: Receive) -> bytes | None:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        try:
            chunk = _BODY_ADAPTER.validate_python(message.get("body", b""))
        except ValidationError:
            return None
        chunks.append(chunk)
        if message.get("more_body") is not True:
            return b"".join(chunks)


def _is_valid_json_rpc_request(body: bytes) -> bool:
    value = _parse_json(body)
    if not isinstance(value, dict):
        return False
    if "id" not in value:
        return True
    request_id = value["id"]
    if isinstance(request_id, bool):
        return False
    if not isinstance(request_id, (int, str)):
        return False
    try:
        profile_lengths = _request_id_profile_lengths(request_id)
    except UnicodeEncodeError:
        return False
    return max(profile_lengths) <= MAX_REQUEST_ID_BYTES


def _parse_json(body: bytes) -> JsonValue | None:
    try:
        return _JSON_VALUE_ADAPTER.validate_python(
            json.loads(
                body,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_nonstandard_json_number,
            )
        )
    except (
        ValueError,
        _DuplicateJsonKeyError,
    ):
        return None


def _scope_string(scope: Scope, key: str) -> str | None:
    try:
        return _SCOPE_STRING_ADAPTER.validate_python(scope.get(key))
    except ValidationError:
        return None


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    value: JsonObject = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError
        value[key] = item
    return value


def _reject_nonstandard_json_number(value: str) -> JsonValue:
    del value
    raise _NonStandardJsonNumberError


def _request_id_profile_lengths(request_id: int | str) -> tuple[int, int]:
    utf8 = json.dumps(
        request_id,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    ascii_escaped = json.dumps(
        request_id,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (len(utf8), len(ascii_escaped))
