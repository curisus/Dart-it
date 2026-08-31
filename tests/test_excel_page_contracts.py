import pytest
from pydantic import ValidationError

from dart_crawler import excel_load_contracts as contracts


def _page_with_row(row: contracts.ExcelRow) -> contracts.ExcelPage:
    return contracts.ExcelPage(
        domain=contracts.ExcelDataDomain.SEARCH_COMPANIES,
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        columns=tuple(row),
        rows=(row,),
        total_rows=1,
        offset=0,
        page_size=1,
        returned_rows=1,
    )


def test_page_dump_has_the_exact_ordered_public_contract() -> None:
    # Given: one successful page at the terminal dataset boundary.
    page = _page_with_row({"value": "complete"})

    # When: the public Pydantic boundary serializes the page.
    dumped = page.model_dump(mode="json")

    # Then: the keys, insertion order, and returned-row count are exact.
    assert tuple(dumped) == (
        "schema_version",
        "domain",
        "request_fingerprint",
        "source_fingerprint",
        "dataset_id",
        "columns",
        "rows",
        "warnings",
        "provenance",
        "total_rows",
        "offset",
        "page_index",
        "page_size",
        "returned_rows",
        "next_cursor",
    )
    assert dumped["returned_rows"] == len(page.rows)


def test_page_request_and_public_models_expose_only_the_fixed_contract() -> None:
    # Given: the fixed schema, cursor, and completed-wire budget versions.
    assert contracts.EXCEL_SCHEMA_VERSION == 1
    assert contracts.EXCEL_CURSOR_VERSION == 1
    assert contracts.EXCEL_PAGE_BUDGET_BYTES == 3_500_000
    assert contracts.DEFAULT_EXCEL_PAGE_SIZE == 1_000
    assert contracts.MAX_EXCEL_PAGE_SIZE == 1_000

    # When: a request omits page_size and the public schemas are inspected.
    request = contracts.ExcelLoadRequest(
        domain=contracts.ExcelDataDomain.SEARCH_COMPANIES,
        arguments={},
    )

    # Then: page_size is strict and obsolete chunk/cell/text fields are absent.
    assert request.page_size == 1_000
    obsolete_page_fields = {
        "chunk_key",
        "chunk_index",
        "returned_cell_count",
        "returned_text_char_count",
        "total_cell_count",
        "total_text_char_count",
    }
    assert obsolete_page_fields.isdisjoint(contracts.ExcelPage.model_fields)
    for invalid_page_size in (True, False, 0, 1_001, 1.0, "1000"):
        with pytest.raises(ValidationError):
            contracts.ExcelLoadRequest.model_validate(
                {
                    "domain": "search_companies",
                    "arguments": {},
                    "page_size": invalid_page_size,
                }
            )


def test_page_model_does_not_reintroduce_excel_only_cell_or_text_caps() -> None:
    # Given: rows just beyond each obsolete response-shape budget.
    wide_row: contracts.ExcelRow = {f"c{index}": 0 for index in range(20_001)}
    long_text_row: contracts.ExcelRow = {"text": "x" * 200_001}

    # When: the normalized page boundary receives each whole row.
    wide_page = _page_with_row(wide_row)
    long_text_page = _page_with_row(long_text_row)

    # Then: only completed JSON-RPC wire bytes, not cells/text, govern selection.
    assert wide_page.returned_rows == 1
    assert long_text_page.rows[0]["text"] == long_text_row["text"]
