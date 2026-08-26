"""Typed request, page, and cursor contracts for Excel-oriented loading."""
# noqa: SIZE_OK

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
from enum import StrEnum, unique
from typing import ClassVar, Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    JsonValue,
    Result,
    WarningInfo,
    error_info,
)

DEFAULT_EXCEL_PAGE_SIZE: Final = 500
MAX_EXCEL_PAGE_ROWS: Final = 1_000
MAX_EXCEL_PAGE_CELLS: Final = 20_000
MAX_EXCEL_PAGE_TEXT_CHARS: Final = 200_000
MAX_EXCEL_PAGE_SERIALIZED_BYTES: Final = 3_500_000
EXCEL_SCHEMA_VERSION: Final = 1
_CURSOR_VERSION: Final = EXCEL_SCHEMA_VERSION

type ExcelScalar = str | int | float | bool | None
type ExcelRow = dict[str, ExcelScalar]


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


@unique
class ExcelPageStatus(StrEnum):
    """Completion state for one bounded page."""

    PARTIAL = "partial"
    COMPLETE = "complete"


class ExcelProvenance(BaseModel):
    """Source information carried with every page."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    source: str = "dart"
    source_fingerprint: str = ""


class ExcelLoadRequest(BaseModel):
    """Boundary model for one Excel page request."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    domain: ExcelDataDomain
    arguments: JsonObject
    page_size: int = Field(
        default=DEFAULT_EXCEL_PAGE_SIZE,
        ge=1,
        le=MAX_EXCEL_PAGE_ROWS,
        strict=True,
    )
    cursor: str | None = None


class ExcelCursorPayload(BaseModel):
    """Signed cursor payload for the next stateless Excel page request."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = _CURSOR_VERSION
    schema_version: Literal[1] = _CURSOR_VERSION
    request_fingerprint: str
    source_fingerprint: str
    chunk_key: str
    chunk_index: int = Field(default=0, ge=0, strict=True)
    offset: int = Field(ge=0, strict=True)
    page_index: int = Field(default=0, ge=0, strict=True)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_ROWS, strict=True)


class ExcelPage(BaseModel):
    """One bounded page of rows safe to return to an Excel client."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = _CURSOR_VERSION
    dataset_id: str = ""
    page_id: str = ""
    page_index: int = Field(default=0, ge=0, strict=True)
    request_fingerprint: str
    source_fingerprint: str
    chunk_key: str
    chunk_index: int = Field(default=0, ge=0, strict=True)
    row_offset: int = Field(ge=0, strict=True)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_ROWS, strict=True)
    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]
    returned_row_count: int = Field(ge=0)
    returned_cell_count: int = Field(ge=0)
    returned_text_char_count: int = Field(ge=0)
    total_row_count: int | None = Field(default=None, ge=0)
    total_cell_count: int | None = Field(default=None, ge=0)
    total_text_char_count: int | None = Field(default=None, ge=0)
    next_cursor: str | None = None
    status: ExcelPageStatus = ExcelPageStatus.COMPLETE
    warnings: tuple[WarningInfo, ...] = ()
    provenance: ExcelProvenance = Field(default_factory=ExcelProvenance)

    @override
    def model_post_init(self, __context: JsonValue, /) -> None:
        normalized_rows = _normalize_rows(self.columns, self.rows)
        object.__setattr__(self, "rows", normalized_rows)
        actual_cell_count = len(self.columns) * len(normalized_rows)
        actual_text_count = sum(
            _text_char_count(value) for row in self.rows for value in row.values()
        )
        if self.returned_row_count != len(normalized_rows):
            msg = "Excel page row count does not match rows"
            raise ValueError(msg)
        if self.returned_cell_count != actual_cell_count:
            msg = "Excel page cell count does not match rows"
            raise ValueError(msg)
        if self.returned_text_char_count != actual_text_count:
            msg = "Excel page text size does not match rows"
            raise ValueError(msg)
        if self.returned_row_count > min(self.page_size, MAX_EXCEL_PAGE_ROWS):
            msg = "Excel page row count exceeds the page budget"
            raise ValueError(msg)
        if self.returned_cell_count > MAX_EXCEL_PAGE_CELLS:
            msg = "Excel page cell count exceeds the page budget"
            raise ValueError(msg)
        if self.returned_text_char_count > MAX_EXCEL_PAGE_TEXT_CHARS:
            msg = "Excel page text size exceeds the page budget"
            raise ValueError(msg)
        _validate_total_counts(self)
        if self.provenance.source_fingerprint == "":
            object.__setattr__(
                self,
                "provenance",
                ExcelProvenance(
                    source=self.provenance.source,
                    source_fingerprint=self.source_fingerprint,
                ),
            )
        elif self.provenance.source_fingerprint != self.source_fingerprint:
            msg = "Excel page provenance does not match the source fingerprint"
            raise ValueError(msg)
        status = (
            ExcelPageStatus.COMPLETE
            if self.next_cursor is None
            else ExcelPageStatus.PARTIAL
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "dataset_id",
            _dataset_id(self.request_fingerprint, self.source_fingerprint),
        )
        object.__setattr__(self, "page_id", _page_id(self))
        if (
            len(self.model_dump_json().encode("utf-8"))
            >= MAX_EXCEL_PAGE_SERIALIZED_BYTES
        ):
            msg = "Excel page serialized payload exceeds the page budget"
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
    schema_version: int = EXCEL_SCHEMA_VERSION,
    chunk_index: int | None = None,
    page_index: int | None = None,
    page_size: int | None = None,
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

    mismatch = _cursor_mismatch_reason(
        payload,
        request_fingerprint=request_fingerprint,
        source_fingerprint=source_fingerprint,
        chunk_key=chunk_key,
        schema_version=schema_version,
        chunk_index=chunk_index,
        page_index=page_index,
        page_size=page_size,
    )
    if mismatch is not None:
        reason, code = mismatch
        return _invalid_cursor(reason, code=code)
    return Result[ExcelCursorPayload].success(payload)


def _invalid_cursor(
    reason: str,
    *,
    code: ErrorCode = ErrorCode.INVALID_INPUT,
) -> Result[ExcelCursorPayload]:
    return Result[ExcelCursorPayload].failure(
        error_info(
            code,
            "Excel page cursor is invalid for this request.",
            retryable=False,
            details={"reason": reason},
        ),
        next_action="Restart the Excel load request without the cursor.",
    )


def _cursor_mismatch_reason(
    payload: ExcelCursorPayload,
    *,
    request_fingerprint: str,
    source_fingerprint: str,
    chunk_key: str,
    schema_version: int,
    chunk_index: int | None,
    page_index: int | None,
    page_size: int | None,
) -> tuple[str, ErrorCode] | None:
    if payload.request_fingerprint != request_fingerprint:
        return ("cursor_request_mismatch", ErrorCode.INVALID_INPUT)
    if payload.source_fingerprint != source_fingerprint:
        return ("cursor_source_mismatch", ErrorCode.VALIDATION_FAILED)
    if payload.chunk_key != chunk_key:
        return ("cursor_chunk_mismatch", ErrorCode.INVALID_INPUT)
    if payload.schema_version != schema_version or payload.version != schema_version:
        return ("cursor_schema_mismatch", ErrorCode.INVALID_INPUT)
    if chunk_index is not None and payload.chunk_index != chunk_index:
        return ("cursor_chunk_index_mismatch", ErrorCode.INVALID_INPUT)
    if page_index is not None and payload.page_index != page_index:
        return ("cursor_page_index_mismatch", ErrorCode.INVALID_INPUT)
    if page_size is not None and payload.page_size != page_size:
        return ("cursor_page_size_mismatch", ErrorCode.INVALID_INPUT)
    return None


def _cursor_payload_json(payload: ExcelCursorPayload) -> bytes:
    cursor: JsonObject = {
        "chunk_key": payload.chunk_key,
        "chunk_index": payload.chunk_index,
        "offset": payload.offset,
        "page_size": payload.page_size,
        "page_index": payload.page_index,
        "request_fingerprint": payload.request_fingerprint,
        "schema_version": payload.schema_version,
        "source_fingerprint": payload.source_fingerprint,
        "version": payload.version,
    }
    return _canonical_json(cursor)


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
        msg = "Base64URL component is not canonical"
        raise binascii.Error(msg)
    return decoded


def _normalize_rows(
    columns: tuple[str, ...],
    rows: tuple[ExcelRow, ...],
) -> tuple[ExcelRow, ...]:
    if len(set(columns)) != len(columns):
        msg = "Excel page columns must be unique"
        raise ValueError(msg)
    normalized: list[ExcelRow] = []
    for row in rows:
        if set(row) != set(columns):
            msg = "Excel page rows must match the ordered columns"
            raise ValueError(msg)
        normalized.append({column: row[column] for column in columns})
    return tuple(normalized)


def _validate_total_counts(page: ExcelPage) -> None:
    if (
        page.total_row_count is not None
        and page.total_row_count < page.returned_row_count
    ):
        msg = "Excel page total row count is below the returned count"
        raise ValueError(msg)
    if (
        page.total_cell_count is not None
        and page.total_cell_count < page.returned_cell_count
    ):
        msg = "Excel page total cell count is below the returned count"
        raise ValueError(msg)
    if (
        page.total_text_char_count is not None
        and page.total_text_char_count < page.returned_text_char_count
    ):
        msg = "Excel page total text size is below the returned count"
        raise ValueError(msg)


def _dataset_id(request_fingerprint: str, source_fingerprint: str) -> str:
    dataset: JsonObject = {
        "request_fingerprint": request_fingerprint,
        "schema_version": EXCEL_SCHEMA_VERSION,
        "source_fingerprint": source_fingerprint,
    }
    return hashlib.sha256(_canonical_json(dataset)).hexdigest()


def _page_id(page: ExcelPage) -> str:
    page_value: JsonObject = {
        "chunk_index": page.chunk_index,
        "chunk_key": page.chunk_key,
        "columns": list(page.columns),
        "dataset_id": page.dataset_id,
        "page_index": page.page_index,
        "row_offset": page.row_offset,
        "rows": [dict(row) for row in page.rows],
        "schema_version": page.schema_version,
    }
    return hashlib.sha256(_canonical_json(page_value)).hexdigest()


def _text_char_count(value: ExcelScalar) -> int:
    match value:  # noqa: MATCH_OK
        case str() as text:
            return len(text)
        case float() as number:
            if not math.isfinite(number):
                msg = "Excel page scalar floats must be finite"
                raise ValueError(msg)
            return 0
        case int() | None:
            return 0
