"""Typed request, page, and cursor contracts for Excel-oriented loading."""

from dart_crawler.excel_cursor import (
    MAX_CURSOR_DECODED_BYTES,
    CursorBinding,
    CursorSecret,
    ExcelCursorPayload,
    cursor_secret_from_environment,
    cursor_secret_from_text,
    decode_excel_cursor,
    encode_excel_cursor,
    fingerprint_excel_request,
)
from dart_crawler.excel_cursor_position import (
    CursorDatasetState,
    validate_cursor_after_query,
)
from dart_crawler.excel_page_models import (
    DEFAULT_EXCEL_PAGE_SIZE,
    EXCEL_CURSOR_VERSION,
    EXCEL_PAGE_BUDGET_BYTES,
    EXCEL_SCHEMA_VERSION,
    MAX_EXCEL_PAGE_ROWS,
    MAX_EXCEL_PAGE_SIZE,
    ExcelDataDomain,
    ExcelLoadRequest,
    ExcelPage,
    ExcelProvenance,
    ExcelRow,
    ExcelScalar,
)
from dart_crawler.excel_request_validation import (
    PreparedExcelRequest,
    prepare_excel_request,
)

__all__ = [
    "DEFAULT_EXCEL_PAGE_SIZE",
    "EXCEL_CURSOR_VERSION",
    "EXCEL_PAGE_BUDGET_BYTES",
    "EXCEL_SCHEMA_VERSION",
    "MAX_CURSOR_DECODED_BYTES",
    "MAX_EXCEL_PAGE_ROWS",
    "MAX_EXCEL_PAGE_SIZE",
    "CursorBinding",
    "CursorDatasetState",
    "CursorSecret",
    "ExcelCursorPayload",
    "ExcelDataDomain",
    "ExcelLoadRequest",
    "ExcelPage",
    "ExcelProvenance",
    "ExcelRow",
    "ExcelScalar",
    "PreparedExcelRequest",
    "cursor_secret_from_environment",
    "cursor_secret_from_text",
    "decode_excel_cursor",
    "encode_excel_cursor",
    "fingerprint_excel_request",
    "prepare_excel_request",
    "validate_cursor_after_query",
]
