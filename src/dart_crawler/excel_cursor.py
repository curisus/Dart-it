from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import ClassVar, Final, Literal, override

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretBytes,
    TypeAdapter,
    ValidationError,
)

from dart_crawler.excel_contract_errors import (
    excel_cursor_configuration_failure,
    excel_failure,
)
from dart_crawler.excel_page_models import (
    EXCEL_CURSOR_VERSION,
    EXCEL_SCHEMA_VERSION,
    MAX_EXCEL_PAGE_SIZE,
    ExcelLoadRequest,
)
from dart_crawler.result import JsonObject, JsonValue, Result

MAX_CURSOR_DECODED_BYTES: Final = 4_096
_FINGERPRINT_PATTERN: Final = r"^[0-9a-f]{64}$"
_HMAC_SHA256_BYTES: Final = 32
_JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class CursorSecret(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    value: SecretBytes = Field(repr=False, min_length=32)


class CursorBinding(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_SIZE)
    schema_version: int = Field(default=EXCEL_SCHEMA_VERSION, ge=1)


class ExcelCursorPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    version: Literal[1] = EXCEL_CURSOR_VERSION
    schema_version: Literal[1] = EXCEL_SCHEMA_VERSION
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    source_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    offset: int = Field(ge=0)
    page_index: int = Field(ge=0)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_SIZE)


class _ExcelCursorWirePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    version: int = Field(ge=1)
    schema_version: int = Field(ge=1)
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    source_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    offset: int = Field(ge=0)
    page_index: int = Field(ge=0)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class _DuplicateJsonKeyError(Exception):
    @override
    def __str__(self) -> str:
        return "duplicate JSON key"


def cursor_secret_from_environment() -> Result[CursorSecret]:
    result = cursor_secret_from_text(os.environ.get(_cursor_environment_variable()))
    if result.data is None:
        return excel_cursor_configuration_failure()
    return result


def cursor_secret_from_text(raw_secret: str | None) -> Result[CursorSecret]:
    if raw_secret is None:
        return excel_failure("invalid_request")
    try:
        secret = CursorSecret(value=SecretBytes(raw_secret.encode("utf-8")))
    except ValidationError:
        return excel_failure("invalid_request")
    return Result[CursorSecret].success(secret)


def fingerprint_excel_request(request: ExcelLoadRequest) -> str:
    normalized: JsonObject = {
        "arguments": request.arguments,
        "domain": request.domain.value,
    }
    return hashlib.sha256(_canonical_json(normalized)).hexdigest()


def encode_excel_cursor(
    payload: ExcelCursorPayload,
    *,
    secret: CursorSecret,
) -> str:
    payload_bytes = _cursor_payload_json(payload)
    signature = hmac.new(
        secret.value.get_secret_value(),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    return f"{_urlsafe_b64encode(payload_bytes)}.{_urlsafe_b64encode(signature)}"


def decode_excel_cursor(
    token: str,
    *,
    secret: CursorSecret,
    binding: CursorBinding,
) -> Result[ExcelCursorPayload]:
    decoded = _decode_token(token)
    if decoded is None:
        return excel_failure("invalid_cursor")
    payload_bytes, signature = decoded
    if len(payload_bytes) + len(signature) > MAX_CURSOR_DECODED_BYTES:
        return excel_failure("invalid_cursor")
    expected_signature = hmac.new(
        secret.value.get_secret_value(),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return excel_failure("invalid_cursor")
    payload = _parse_cursor_payload(payload_bytes)
    if payload is None or payload_bytes != _cursor_payload_json(payload):
        return excel_failure("invalid_cursor")
    if (
        payload.version != EXCEL_CURSOR_VERSION
        or payload.schema_version != binding.schema_version
    ):
        return excel_failure("cursor_schema_mismatch")
    if payload.request_fingerprint != binding.request_fingerprint:
        return excel_failure("cursor_request_mismatch")
    if payload.page_size != binding.page_size:
        return excel_failure("cursor_page_size_mismatch")
    try:
        validated_payload = ExcelCursorPayload.model_validate(payload.model_dump())
    except ValidationError:
        return excel_failure("invalid_cursor")
    return Result[ExcelCursorPayload].success(validated_payload)


def _decode_token(token: str) -> tuple[bytes, bytes] | None:
    try:
        if len(token.encode("utf-8")) > MAX_CURSOR_DECODED_BYTES:
            return None
    except UnicodeEncodeError:
        return None
    components = token.split(".")
    if len(components) != 2:
        return None
    payload_part, signature_part = components
    try:
        payload_bytes = _urlsafe_b64decode(payload_part)
        signature = _urlsafe_b64decode(signature_part)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return None
    if len(signature) != _HMAC_SHA256_BYTES:
        return None
    return (payload_bytes, signature)


def _parse_cursor_payload(payload_bytes: bytes) -> _ExcelCursorWirePayload | None:
    try:
        decoded = payload_bytes.decode("utf-8")
        value = _JSON_VALUE_ADAPTER.validate_python(
            json.loads(decoded, object_pairs_hook=_unique_json_object)
        )
        return _ExcelCursorWirePayload.model_validate(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateJsonKeyError,
        ValidationError,
    ):
        return None


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    value: JsonObject = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError
        value[key] = item
    return value


def _cursor_payload_json(
    payload: ExcelCursorPayload | _ExcelCursorWirePayload,
) -> bytes:
    value: JsonObject = {
        "offset": payload.offset,
        "page_index": payload.page_index,
        "page_size": payload.page_size,
        "request_fingerprint": payload.request_fingerprint,
        "schema_version": payload.schema_version,
        "source_fingerprint": payload.source_fingerprint,
        "version": payload.version,
    }
    return _canonical_json(value)


def _canonical_json(value: JsonObject) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    decoded = base64.b64decode(
        f"{encoded}{padding}".encode("ascii"),
        altchars=b"-_",
        validate=True,
    )
    if _urlsafe_b64encode(decoded) != encoded:
        raise binascii.Error
    return decoded


def _cursor_environment_variable() -> str:
    return "DART_MCP_CURSOR_SECRET"
