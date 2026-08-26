import base64
from math import inf, nan
from typing import Literal, TypedDict

import pytest
from pydantic import ValidationError

from dart_crawler.excel_load_contracts import (
    DEFAULT_EXCEL_PAGE_SIZE,
    MAX_EXCEL_PAGE_CELLS,
    MAX_EXCEL_PAGE_ROWS,
    MAX_EXCEL_PAGE_SERIALIZED_BYTES,
    MAX_EXCEL_PAGE_TEXT_CHARS,
    ExcelCursorPayload,
    ExcelDataDomain,
    ExcelLoadRequest,
    ExcelPage,
    ExcelPageStatus,
    ExcelProvenance,
    ExcelRow,
    decode_excel_cursor,
    encode_excel_cursor,
    fingerprint_excel_request,
)
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    JsonValue,
    WarningCode,
    WarningInfo,
)


class PageKwargs(TypedDict):
    schema_version: Literal[1]
    dataset_id: str
    page_id: str
    page_index: int
    request_fingerprint: str
    source_fingerprint: str
    chunk_key: str
    chunk_index: int
    row_offset: int
    page_size: int
    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]
    returned_row_count: int
    returned_cell_count: int
    returned_text_char_count: int
    total_row_count: int
    total_cell_count: int
    total_text_char_count: int
    next_cursor: str | None
    status: ExcelPageStatus
    warnings: tuple[WarningInfo, ...]
    provenance: ExcelProvenance


_DEFAULT_ROWS: tuple[ExcelRow, ...] = ({"account": "cash", "amount": "1"},)


def _numeric_row(key: str, value: int) -> ExcelRow:
    return {key: value}


def _two_numeric_row(first_key: str, second_key: str, value: int) -> ExcelRow:
    return {first_key: value, second_key: value}


def _wide_numeric_row(columns: tuple[str, ...], value: int) -> ExcelRow:
    return dict.fromkeys(columns, value)


def _page_kwargs(
    *,
    rows: tuple[ExcelRow, ...] = _DEFAULT_ROWS,
    columns: tuple[str, ...] = ("account", "amount"),
    next_cursor: str | None = None,
    page_size: int = DEFAULT_EXCEL_PAGE_SIZE,
) -> PageKwargs:
    return {
        "schema_version": 1,
        "dataset_id": "placeholder-dataset",
        "page_id": "placeholder-page",
        "page_index": 0,
        "request_fingerprint": "request",
        "source_fingerprint": "source",
        "chunk_key": "chunk",
        "chunk_index": 0,
        "row_offset": 0,
        "page_size": page_size,
        "columns": columns,
        "rows": rows,
        "returned_row_count": len(rows),
        "returned_cell_count": sum(len(row) for row in rows),
        "returned_text_char_count": sum(
            len(value)
            for row in rows
            for value in row.values()
            if isinstance(value, str)
        ),
        "total_row_count": len(rows),
        "total_cell_count": sum(len(row) for row in rows),
        "total_text_char_count": sum(
            len(value)
            for row in rows
            for value in row.values()
            if isinstance(value, str)
        ),
        "next_cursor": next_cursor,
        "status": (
            ExcelPageStatus.PARTIAL
            if next_cursor is not None
            else ExcelPageStatus.COMPLETE
        ),
        "warnings": (
            WarningInfo(
                code=WarningCode.PARTIAL_COLLECTION,
                message="fixture warning",
            ),
        ),
        "provenance": ExcelProvenance(
            source="fixture",
            source_fingerprint="source",
        ),
    }


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
        _ = ExcelLoadRequest.model_validate({"domain": "unknown_tool", "arguments": {}})

    with pytest.raises(ValidationError):
        _ = ExcelLoadRequest(
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
    assert token == encode_excel_cursor(payload, secret=b"cursor-secret")
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


def test_cursor_rejects_noncanonical_equivalent_payload_and_signature() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments={"corp_codes": ["00126380"], "bsns_year": 2025},
        page_size=250,
    )
    payload = ExcelCursorPayload(
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="xx",
        offset=250,
        page_size=250,
    )
    token = encode_excel_cursor(payload, secret=b"cursor-secret")
    parts = token.split(".")

    def decode_component(component: str) -> bytes:
        padded = f"{component}{'=' * (-len(component) % 4)}"
        return base64.urlsafe_b64decode(padded.encode("ascii"))

    def equivalent_component(component: str) -> str:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        last_index = alphabet.index(component[-1])
        unused_bits = {0: 0, 1: 0, 2: 4, 3: 2}[len(component) % 4]
        for candidate_index, candidate in enumerate(alphabet):
            if candidate_index == last_index:
                continue
            if candidate_index >> unused_bits != last_index >> unused_bits:
                continue
            replacement = f"{component[:-1]}{candidate}"
            if decode_component(replacement) == decode_component(component):
                return replacement
        msg = "fixture must have an equivalent noncanonical symbol"
        raise AssertionError(msg)

    for component_index in (0, 1):
        variant_parts = list(parts)
        variant_parts[component_index] = equivalent_component(
            variant_parts[component_index]
        )
        variant = ".".join(variant_parts)
        assert variant != token
        assert decode_component(variant_parts[component_index]) == decode_component(
            parts[component_index]
        )

        result = decode_excel_cursor(
            variant,
            secret=b"cursor-secret",
            request_fingerprint=fingerprint_excel_request(request),
            source_fingerprint="source-sha256",
            chunk_key="xx",
        )

        assert result.ok is False
        assert result.error is not None
        assert result.error.code is ErrorCode.INVALID_INPUT
        assert result.error.retryable is False
        assert "cursor-secret" not in str(result.error)


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
    assert mismatch.error is not None
    assert mismatch.error.code is ErrorCode.INVALID_INPUT
    assert stale_source.error is not None
    assert stale_source.error.code is ErrorCode.VALIDATION_FAILED
    assert wrong_chunk.error is not None
    assert wrong_chunk.error.code is ErrorCode.INVALID_INPUT


def test_cursor_binds_schema_page_and_chunk_position() -> None:
    request = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments={"corp_code": "00126380"},
        page_size=250,
    )
    payload = ExcelCursorPayload(
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-sha256",
        chunk_index=3,
        offset=250,
        page_index=1,
        page_size=250,
        schema_version=1,
    )
    token = encode_excel_cursor(payload, secret=b"cursor-secret")

    decoded = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-sha256",
        schema_version=1,
        chunk_index=3,
        page_index=1,
        page_size=250,
    )
    wrong_page = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-sha256",
        schema_version=1,
        chunk_index=3,
        page_index=2,
        page_size=250,
    )
    wrong_schema = decode_excel_cursor(
        token,
        secret=b"cursor-secret",
        request_fingerprint=fingerprint_excel_request(request),
        source_fingerprint="source-sha256",
        chunk_key="chunk-sha256",
        schema_version=2,
        chunk_index=3,
        page_index=1,
        page_size=250,
    )

    assert decoded.ok is True
    assert decoded.data == payload
    assert wrong_page.ok is False
    assert wrong_page.error is not None
    assert wrong_page.error.code is ErrorCode.INVALID_INPUT
    assert wrong_schema.ok is False
    assert wrong_schema.error is not None
    assert wrong_schema.error.code is ErrorCode.INVALID_INPUT


def test_page_has_deterministic_ids_and_explicit_metadata() -> None:
    first = ExcelPage(**_page_kwargs(next_cursor="next"))
    second = ExcelPage(**_page_kwargs(next_cursor="next"))

    assert first.schema_version == 1
    assert first.page_index == 0
    assert first.status.value == "partial"
    assert first.warnings[0].code is WarningCode.PARTIAL_COLLECTION
    assert first.provenance.source == "fixture"
    assert first.provenance.source_fingerprint == "source"
    assert first.total_row_count == 1
    assert first.total_cell_count == 2
    assert first.total_text_char_count == 5
    assert first.dataset_id == second.dataset_id
    assert first.page_id == second.page_id
    assert first.model_dump_json().encode("utf-8") == second.model_dump_json().encode(
        "utf-8"
    )

    next_page = ExcelPage(
        **_page_kwargs(
            rows=({"account": "bank", "amount": "2"},),
            next_cursor=None,
        )
    )
    assert next_page.dataset_id == first.dataset_id
    assert next_page.page_id != first.page_id


def test_page_normalizes_row_order_and_rejects_nested_or_nonfinite_values() -> None:
    reordered_row: ExcelRow = {"amount": 1, "account": "cash"}
    page = ExcelPage(**_page_kwargs(rows=(reordered_row,)))

    assert tuple(page.rows[0]) == ("account", "amount")
    assert page.rows[0]["amount"] == 1

    nested_rows: list[JsonValue] = [
        {"account": {"name": "cash"}, "amount": 1},
    ]
    nested_page: JsonObject = {
        "request_fingerprint": "request",
        "source_fingerprint": "source",
        "chunk_key": "chunk",
        "row_offset": 0,
        "page_size": 500,
        "columns": ["account", "amount"],
        "rows": nested_rows,
        "returned_row_count": 1,
        "returned_cell_count": 2,
        "returned_text_char_count": 4,
        "next_cursor": None,
    }
    with pytest.raises(ValidationError):
        _ = ExcelPage.model_validate(nested_page)

    nan_rows: list[JsonValue] = [{"account": "cash", "amount": nan}]
    with pytest.raises(ValidationError):
        _ = ExcelPage.model_validate(
            {
                **nested_page,
                "rows": nan_rows,
                "returned_text_char_count": 4,
            }
        )

    inf_rows: list[JsonValue] = [{"account": "cash", "amount": inf}]
    with pytest.raises(ValidationError):
        _ = ExcelPage.model_validate(
            {
                **nested_page,
                "rows": inf_rows,
                "returned_text_char_count": 4,
            }
        )


def test_page_preserves_bool_as_bool_and_enforces_column_shape() -> None:
    bool_row: ExcelRow = {"active": True, "account": "cash"}
    page = ExcelPage(
        **_page_kwargs(
            columns=("account", "active"),
            rows=(bool_row,),
        )
    )

    assert page.rows[0]["active"] is True
    assert type(page.rows[0]["active"]) is bool

    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=("account", "active"),
                rows=({"account": "cash"},),
            )
        )


def test_page_accepts_exact_row_budget_and_rejects_over_budget() -> None:
    exact_rows = tuple(
        _numeric_row("value", index) for index in range(MAX_EXCEL_PAGE_ROWS)
    )
    exact_page = ExcelPage(
        **_page_kwargs(
            columns=("value",),
            rows=exact_rows,
            page_size=MAX_EXCEL_PAGE_ROWS,
        )
    )

    assert exact_page.returned_row_count == MAX_EXCEL_PAGE_ROWS

    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=("value",),
                rows=(*exact_rows, {"value": MAX_EXCEL_PAGE_ROWS}),
                page_size=MAX_EXCEL_PAGE_ROWS,
            )
        )


def test_page_accepts_exact_cell_budget_and_rejects_over_budget() -> None:
    exact_columns = tuple(f"field_{index:02d}" for index in range(20))
    exact_rows = tuple(
        _wide_numeric_row(exact_columns, row) for row in range(MAX_EXCEL_PAGE_ROWS)
    )
    exact_page = ExcelPage(
        **_page_kwargs(
            columns=exact_columns,
            rows=exact_rows,
            page_size=MAX_EXCEL_PAGE_ROWS,
        )
    )

    assert exact_page.returned_cell_count == MAX_EXCEL_PAGE_CELLS

    over_columns = (*exact_columns, "field_20")
    over_rows = tuple(
        _wide_numeric_row(over_columns, row) for row in range(MAX_EXCEL_PAGE_ROWS)
    )
    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=over_columns,
                rows=over_rows,
                page_size=MAX_EXCEL_PAGE_ROWS,
            )
        )


def test_page_accepts_exact_text_budget_and_rejects_over_budget() -> None:
    exact_text = "x" * MAX_EXCEL_PAGE_TEXT_CHARS
    exact_page = ExcelPage(
        **_page_kwargs(
            columns=("text",),
            rows=({"text": exact_text},),
        )
    )

    assert exact_page.returned_text_char_count == MAX_EXCEL_PAGE_TEXT_CHARS

    with pytest.raises(ValidationError):
        _ = ExcelPage(
        **_page_kwargs(
            columns=("text",),
            rows=({"text": f"{exact_text}x"},),
            )
        )


def test_page_serialized_budget_uses_stable_json_bytes() -> None:
    columns = tuple(f"field_{index:02d}" for index in range(20))

    def page_for_numeric_digits(digits: int) -> ExcelPage:
        value = int("9" * digits)
        rows = tuple(
            _wide_numeric_row(columns, value) for _ in range(MAX_EXCEL_PAGE_ROWS)
        )
        return ExcelPage(
            **_page_kwargs(
                columns=columns,
                rows=rows,
                page_size=MAX_EXCEL_PAGE_ROWS,
            )
        )

    page_before_boundary = page_for_numeric_digits(162)
    serialized = page_before_boundary.model_dump_json().encode("utf-8")

    assert serialized == page_before_boundary.model_dump_json().encode("utf-8")
    assert len(serialized) < MAX_EXCEL_PAGE_SERIALIZED_BYTES
    assert (
        MAX_EXCEL_PAGE_SERIALIZED_BYTES - len(serialized)
    ) < 20_000

    with pytest.raises(ValidationError):
        _ = page_for_numeric_digits(163)


def test_page_contract_rejects_all_over_budget_shapes() -> None:
    row: ExcelRow = {"account": "cash", "amount": "1"}
    page = ExcelPage(**_page_kwargs(rows=(row,)))

    assert page.returned_row_count == 1

    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=("value",),
                rows=tuple(_numeric_row("value", index) for index in range(1_001)),
                page_size=MAX_EXCEL_PAGE_ROWS,
            )
        )

    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=("a", "b"),
                rows=tuple(
                    _two_numeric_row("a", "b", index) for index in range(10_001)
                ),
                page_size=MAX_EXCEL_PAGE_ROWS,
            )
        )

    too_many_cell_columns = tuple(f"column_{column}" for column in range(21))
    too_many_cells = tuple(
        _wide_numeric_row(too_many_cell_columns, row) for row in range(1_000)
    )
    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=too_many_cell_columns,
                rows=too_many_cells,
                page_size=MAX_EXCEL_PAGE_ROWS,
            )
        )

    with pytest.raises(ValidationError):
        _ = ExcelPage(
            **_page_kwargs(
                columns=("text",),
                rows=({"text": "x" * 200_001},),
            )
        )
