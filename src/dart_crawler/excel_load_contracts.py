"""Typed request, page, and cursor contracts for Excel-oriented loading."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from enum import StrEnum, unique
from typing import Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dart_crawler.result import ErrorCode, JsonObject, JsonValue, Result, error_info

DEFAULT_EXCEL_PAGE_SIZE: Final = 500
MAX_EXCEL_PAGE_ROWS: Final = 1_000
MAX_EXCEL_PAGE_CELLS: Final = 20_000
MAX_EXCEL_PAGE_TEXT_CHARS: Final = 200_000
_CURSOR_VERSION: Final = 1


@unique
class ExcelDataDomain(StrEnum):
    """Read-only MCP tool domains that can be loaded page-by-page into Excel."""

    SEARCH_COMPANIES = "search_companies"
    LIST_REPORT_FILINGS = "list_report_filings"
    LIST_REPORT_ATTACHMENTS = "list_report_attachments"
    LIST_REPORT_SECTIONS = "list_report_sections"
    GET_REPORT_SECTIONS = "get_report_sections"
    GET_FINANCIAL_STATEMENTS = "get_financial_statements"
    GET_MAJOR_ACCOUNTS = "get_major_accounts"
    GET_FINANCIAL_INDICATORS = "get_financial_indicators"
    GET_REPORT_TOPICS = "get_report_topics"
    GET_COMPANY_PROFILE = "get_company_profile"
    GET_OWNERSHIP_REPORTS = "get_ownership_reports"
    GET_MATERIAL_EVENTS = "get_material_events"
    GET_REGISTRATION_STATEMENTS = "get_registration_statements"


class ExcelLoadRequest(BaseModel):
    """Boundary model for one Excel page request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: ExcelDataDomain
    arguments: JsonObject
    page_size: int = Field(default=DEFAULT_EXCEL_PAGE_SIZE, ge=1, le=MAX_EXCEL_PAGE_ROWS)
    cursor: str | None = None


class ExcelCursorPayload(BaseModel):
    """Signed cursor payload for the next stateless Excel page request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = _CURSOR_VERSION
    request_fingerprint: str
    source_fingerprint: str
    chunk_key: str
    offset: int = Field(ge=0)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_ROWS)


class ExcelPage(BaseModel):
    """One bounded page of rows safe to return to an Excel client."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_fingerprint: str
    source_fingerprint: str
    chunk_key: str
    row_offset: int = Field(ge=0)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_ROWS)
    columns: tuple[str, ...]
    rows: tuple[JsonObject, ...]
    returned_row_count: int = Field(ge=0)
    returned_cell_count: int = Field(ge=0)
    returned_text_char_count: int = Field(ge=0)
    next_cursor: str | None

    def model_post_init(self, __context: JsonValue, /) -> None:
        actual_cell_count = sum(len(row) for row in self.rows)
        actual_text_count = sum(
            _text_char_count(value) for row in self.rows for value in row.values()
        )
        if self.returned_row_count != len(self.rows):
            msg = "Excel page row count does not match rows"
            raise ValueError(msg)
        if self.returned_cell_count != actual_cell_count:
            msg = "Excel page cell count does not match rows"
            raise ValueError(msg)
        if self.returned_text_char_count != actual_text_count:
            msg = "Excel page text size does not match rows"
            raise ValueError(msg)
        if self.returned_row_count > MAX_EXCEL_PAGE_ROWS:
            msg = "Excel page row count exceeds the page budget"
            raise ValueError(msg)
        if self.returned_cell_count > MAX_EXCEL_PAGE_CELLS:
            msg = "Excel page cell count exceeds the page budget"
            raise ValueError(msg)
        if self.returned_text_char_count > MAX_EXCEL_PAGE_TEXT_CHARS:
            msg = "Excel page text size exceeds the page budget"
            raise ValueError(msg)


def fingerprint_excel_request(request: ExcelLoadRequest) -> str:
    """Return a stable request fingerprint that deliberately ignores cursor."""
    normalized: JsonObject = {
        "arguments": request.arguments,
        "domain": request.domain.value,
        "page_size": request.page_size,
    }
    return hashlib.sha256(_canonical_json(normalized)).hexdigest()


def encode_excel_cursor(payload: ExcelCursorPayload, *, secret: bytes) -> str:
    """Sign and encode a cursor payload."""
    payload_bytes = _cursor_payload_json(payload)
    signature = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    return f"{_urlsafe_b64encode(payload_bytes)}.{_urlsafe_b64encode(signature)}"


def decode_excel_cursor(
    token: str,
    *,
    secret: bytes,
    request_fingerprint: str,
    source_fingerprint: str,
    chunk_key: str,
) -> Result[ExcelCursorPayload]:
    """Decode a cursor only when its signature and binding fields match."""
    try:
        payload_part, signature_part = token.split(".", maxsplit=1)
        payload_bytes = _urlsafe_b64decode(payload_part)
        signature = _urlsafe_b64decode(signature_part)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return _invalid_cursor("malformed_cursor")

    expected_signature = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return _invalid_cursor("cursor_signature_mismatch")

    try:
        payload = ExcelCursorPayload.model_validate_json(payload_bytes)
    except ValidationError:
        return _invalid_cursor("cursor_payload_invalid")

    if payload.request_fingerprint != request_fingerprint:
        return _invalid_cursor("cursor_request_mismatch")
    if payload.source_fingerprint != source_fingerprint:
        return _invalid_cursor("cursor_source_mismatch")
    if payload.chunk_key != chunk_key:
        return _invalid_cursor("cursor_chunk_mismatch")
    return Result[ExcelCursorPayload].success(payload)


def _invalid_cursor(reason: str) -> Result[ExcelCursorPayload]:
    return Result[ExcelCursorPayload].failure(
        error_info(
            ErrorCode.INVALID_INPUT,
            "Excel page cursor is invalid for this request.",
            retryable=False,
            details={"reason": reason},
        ),
        next_action="Restart the Excel load request without the cursor.",
    )


def _cursor_payload_json(payload: ExcelCursorPayload) -> bytes:
    cursor: JsonObject = {
        "chunk_key": payload.chunk_key,
        "offset": payload.offset,
        "page_size": payload.page_size,
        "request_fingerprint": payload.request_fingerprint,
        "source_fingerprint": payload.source_fingerprint,
        "version": payload.version,
    }
    return _canonical_json(cursor)


def _canonical_json(value: JsonObject) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}".encode("ascii"))


def _text_char_count(value: JsonValue) -> int:
    match value:
        case str() as text:
            return len(text)
        case int() | float() | bool() | None:
            return 0
        case list() as items:
            return sum(_text_char_count(item) for item in items)
        case dict() as mapping:
            return sum(_text_char_count(item) for item in mapping.values())
        case _ as unreachable:
            assert_never(unreachable)
