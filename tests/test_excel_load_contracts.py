import pytest
from pydantic import ValidationError

from dart_crawler.excel_load_contracts import (
    DEFAULT_EXCEL_PAGE_SIZE,
    ExcelCursorPayload,
    ExcelDataDomain,
    ExcelLoadRequest,
    ExcelPage,
    decode_excel_cursor,
    encode_excel_cursor,
    fingerprint_excel_request,
)
from dart_crawler.result import ErrorCode, JsonObject


def _numeric_row(key: str, value: int) -> JsonObject:
    return {key: value}


def _two_numeric_row(first_key: str, second_key: str, value: int) -> JsonObject:
    return {first_key: value, second_key: value}


def test_request_fingerprint_is_stable_and_ignores_cursor() -> None:
    first = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_COMPANY_PROFILE,
        arguments={"corp_code": "00126380", "nested": {"b": 2, "a": 1}},
        cursor="old-cursor",
    )
    second = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_COMPANY_PROFILE,
        arguments={"nested": {"a": 1, "b": 2}, "corp_code": "00126380"},
        cursor="new-cursor",
    )

    assert fingerprint_excel_request(first) == fingerprint_excel_request(second)
    assert first.page_size == DEFAULT_EXCEL_PAGE_SIZE


def test_request_rejects_unknown_domain_and_oversized_page() -> None:
    with pytest.raises(ValidationError):
        ExcelLoadRequest.model_validate({"domain": "unknown_tool", "arguments": {}})

    with pytest.raises(ValidationError):
        ExcelLoadRequest(
            domain=ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
            arguments={"corp_code": "00126380"},
            page_size=1_001,
        )


def test_cursor_round_trips_and_rejects_tampering() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments={"corp_codes": ["00126380"], "bsns_year": 2025},
        page_size=250,
    )
    payload = ExcelCursorPayload(
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-0001",
        offset=250,
        page_size=250,
    )

    token = encode_excel_cursor(payload, secret=b"cursor-secret")
    decoded = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-0001",
    )
    tampered = decode_excel_cursor(
        f"{token[:-1]}A",
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-0001",
    )

    assert decoded.ok is True
    assert decoded.data == payload
    assert tampered.ok is False
    assert tampered.error is not None
    assert tampered.error.code is ErrorCode.INVALID_INPUT


def test_cursor_rejects_request_source_and_chunk_mismatches() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_REPORT_TOPICS,
        arguments={"corp_code": "00126380", "topics": ["audit_opinion"]},
    )
    token = encode_excel_cursor(
        ExcelCursorPayload(
            request_fingerprint=fingerprint_excel_request(request),
            source_fingerprint="source-v1",
            chunk_key="chunk-a",
            offset=500,
            page_size=500,
        ),
        secret=b"cursor-secret",
    )

    mismatch = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint="different-request",
        source_fingerprint="source-v1",
        chunk_key="chunk-a",
    )
    stale_source = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-v2",
        chunk_key="chunk-a",
    )
    wrong_chunk = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-v1",
        chunk_key="chunk-b",
    )

    for result in (mismatch, stale_source, wrong_chunk):
        assert result.ok is False
        assert result.error is not None
        assert result.error.code is ErrorCode.INVALID_INPUT


def test_page_contract_bounds_rows_cells_and_text() -> None:
    row: JsonObject = {"account": "cash", "amount": "1"}
    page = ExcelPage(
        request_fingerprint="request",
        source_fingerprint="source",
        chunk_key="chunk",
        row_offset=0,
        page_size=500,
        columns=("account", "amount"),
        rows=(row,),
        returned_row_count=1,
        returned_cell_count=2,
        returned_text_char_count=5,
        next_cursor=None,
    )

    assert page.returned_row_count == 1

    with pytest.raises(ValidationError):
        ExcelPage(
            request_fingerprint="request",
            source_fingerprint="source",
            chunk_key="chunk",
            row_offset=0,
            page_size=1_000,
            columns=("value",),
            rows=tuple(_numeric_row("value", index) for index in range(1_001)),
            returned_row_count=1_001,
            returned_cell_count=1_001,
            returned_text_char_count=0,
            next_cursor=None,
        )

    with pytest.raises(ValidationError):
        ExcelPage(
            request_fingerprint="request",
            source_fingerprint="source",
            chunk_key="chunk",
            row_offset=0,
            page_size=1_000,
            columns=("a", "b"),
            rows=tuple(
                _two_numeric_row("a", "b", index) for index in range(10_001)
            ),
            returned_row_count=10_001,
            returned_cell_count=20_002,
            returned_text_char_count=0,
            next_cursor=None,
        )

    with pytest.raises(ValidationError):
        ExcelPage(
            request_fingerprint="request",
            source_fingerprint="source",
            chunk_key="chunk",
            row_offset=0,
            page_size=1,
            columns=("text",),
            rows=({"text": "x" * 200_001},),
            returned_row_count=1,
            returned_cell_count=1,
            returned_text_char_count=200_001,
            next_cursor=None,
        )
