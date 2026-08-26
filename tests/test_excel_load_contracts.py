from math import inf, nan

import pytest
from pydantic import ValidationError

from dart_crawler.excel_load_contracts import (
    DEFAULT_EXCEL_PAGE_SIZE,
    MAX_EXCEL_PAGE_SIZE,
    ExcelDataDomain,
    ExcelLoadRequest,
    ExcelPage,
    ExcelProvenance,
    fingerprint_excel_request,
)


def _page(
    *,
    rows: tuple[dict[str, str | int | float | bool | None], ...] = (
        {"account": "cash", "amount": 1},
    ),
    columns: tuple[str, ...] = ("account", "amount"),
) -> ExcelPage:
    return ExcelPage(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        columns=columns,
        rows=rows,
        total_rows=len(rows),
        offset=0,
        page_size=DEFAULT_EXCEL_PAGE_SIZE,
        returned_rows=len(rows),
    )


def test_request_fingerprint_is_stable_and_ignores_cursor() -> None:
    first = ExcelLoadRequest(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        arguments={"corp_code": "00126380", "year": 2025},
        cursor="first-token",
    )
    second = first.model_copy(update={"cursor": "second-token"})

    assert fingerprint_excel_request(first) == fingerprint_excel_request(second)
    assert len(fingerprint_excel_request(first)) == 64


@pytest.mark.parametrize(
    "page_size",
    [
        pytest.param(0, id="zero"),
        pytest.param(MAX_EXCEL_PAGE_SIZE + 1, id="above-maximum"),
        pytest.param(True, id="boolean"),
        pytest.param(1.0, id="float"),
    ],
)
def test_request_rejects_non_strict_or_out_of_range_page_size(
    page_size: float | bool,
) -> None:
    with pytest.raises(ValidationError):
        ExcelLoadRequest.model_validate(
            {
                "domain": ExcelDataDomain.SEARCH_COMPANIES.value,
                "arguments": {},
                "page_size": page_size,
            }
        )


def test_request_rejects_unknown_domain() -> None:
    with pytest.raises(ValidationError):
        ExcelLoadRequest.model_validate(
            {"domain": "unknown", "arguments": {}, "page_size": 1}
        )


def test_page_has_deterministic_ids_and_explicit_metadata() -> None:
    first = _page()
    second = _page()

    assert first.dataset_id == second.dataset_id
    assert len(first.dataset_id) == 64
    assert first.domain is ExcelDataDomain.GET_MAJOR_ACCOUNTS
    assert first.returned_rows == len(first.rows)
    assert first.next_cursor is None
    assert first.provenance == ExcelProvenance(
        source="dart",
        source_fingerprint="b" * 64,
    )


def test_page_normalizes_row_order_and_preserves_boolean_scalars() -> None:
    page = _page(
        columns=("account", "amount", "audited"),
        rows=({"audited": True, "amount": 1, "account": "cash"},),
    )

    assert tuple(page.rows[0]) == ("account", "amount", "audited")
    assert page.rows[0]["audited"] is True


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(({"account": "cash", "amount": nan},), id="nan"),
        pytest.param(({"account": "cash", "amount": inf},), id="infinity"),
        pytest.param(({"account": "cash"},), id="missing-column"),
        pytest.param(
            ({"account": "cash", "amount": 1, "extra": "x"},),
            id="extra-column",
        ),
        pytest.param(({"account": "cash", "amount": ["nested"]},), id="nested"),
    ],
)
def test_page_rejects_nonfinite_nested_or_mismatched_rows(
    rows: tuple[dict[str, str | int | float | bool | None], ...],
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _page(rows=rows)


def test_page_rejects_non_hash_fingerprints() -> None:
    with pytest.raises(ValidationError):
        ExcelPage(
            domain=ExcelDataDomain.SEARCH_COMPANIES,
            request_fingerprint="https://example.invalid/secret",
            source_fingerprint="C:/private/source.xlsx",
            columns=(),
            rows=(),
            total_rows=0,
            offset=0,
            page_size=1,
            returned_rows=0,
        )


def test_public_page_contract_has_no_obsolete_chunk_or_cell_text_caps() -> None:
    assert set(ExcelPage.model_fields).isdisjoint(
        {
            "chunk_key",
            "chunk_index",
            "returned_cell_count",
            "returned_text_char_count",
            "total_cell_count",
            "total_text_char_count",
        }
    )
