from dart_crawler.excel_company_arguments import SearchCompaniesArguments
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
)
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_row_normalization import (
    CellFailure,
    ExcelSourceValue,
    NormalizedCell,
    NormalizedExcelTable,
    PendingExcelRow,
    ScalarKind,
    normalize_excel_cell,
    normalize_excel_rows,
)
from dart_crawler.normalized_excel_models import NormalizedExcelProvenance
from dart_crawler.result import ErrorCode


def _table(
    context_columns: tuple[str, ...],
    source_columns: tuple[str, ...],
    rows: tuple[PendingExcelRow, ...],
) -> NormalizedExcelTable:
    result = normalize_excel_rows(context_columns, source_columns, rows)
    match result:
        case NormalizedExcelTable() as table:
            return table
        case CellFailure(reason=reason):
            raise AssertionError(reason)


def test_collision_suffix_chain_reserves_original_source_columns() -> None:
    source_pairs = (
        ("name", "source value"),
        ("source_name", "literal first suffix"),
        ("source_name_2", "literal second suffix"),
        ("매우 긴 열 이름 🧪", "unicode"),
    )

    table = _table(
        ("name",),
        tuple(name for name, _value in source_pairs),
        (PendingExcelRow((("name", "context value"),), source_pairs),),
    )

    assert table.columns == (
        "name",
        "source_name_3",
        "source_name",
        "source_name_2",
        "매우 긴 열 이름 🧪",
    )
    assert table.rows[0]["name"] == "context value"
    assert table.rows[0]["source_name_3"] == "source value"
    assert table.rows[0]["source_name"] == "literal first suffix"


def test_equal_same_typed_scalar_reuses_context_column() -> None:
    equal = _table(
        ("ranking",),
        ("ranking",),
        (PendingExcelRow((("ranking", 1),), (("ranking", 1),)),),
    )
    bool_collision = _table(
        ("ranking",),
        ("ranking",),
        (PendingExcelRow((("ranking", 1),), (("ranking", True),)),),
    )

    assert equal.columns == ("ranking",)
    assert equal.rows == ({"ranking": 1},)
    assert bool_collision.columns == ("ranking", "source_ranking")
    assert bool_collision.rows[0]["ranking"] == 1
    assert bool_collision.rows[0]["source_ranking"] is True


def test_dynamic_columns_follow_first_seen_source_order() -> None:
    table = _table(
        ("context",),
        (),
        (
            PendingExcelRow(
                (("context", "first"),),
                (("beta", 2), ("alpha", 1)),
            ),
            PendingExcelRow(
                (("context", "second"),),
                (("gamma", 3), ("beta", 4)),
            ),
        ),
    )

    assert table.columns == ("context", "beta", "alpha", "gamma")
    assert table.rows == (
        {"context": "first", "beta": 2, "alpha": 1, "gamma": None},
        {"context": "second", "beta": 4, "alpha": None, "gamma": 3},
    )


def test_nested_json_is_compact_sorted_and_preserves_list_order() -> None:
    nested: ExcelSourceValue = {
        "z": 1,
        "a": [3, {"b": 2, "a": 1}],
    }

    result = normalize_excel_cell(nested)

    match result:
        case NormalizedCell(value=value):
            assert value == '{"a":[3,{"a":1,"b":2}],"z":1}'
        case CellFailure(reason=reason):
            raise AssertionError(reason)
    assert nested == {"z": 1, "a": [3, {"b": 2, "a": 1}]}


def test_scalar_cells_remain_scalars_with_bool_distinct_from_int() -> None:
    values = (True, 7, 2.5, "7", None)
    normalized = tuple(normalize_excel_cell(value) for value in values)

    assert normalized == (
        NormalizedCell(value=True, scalar_kind=ScalarKind.BOOLEAN),
        NormalizedCell(value=7, scalar_kind=ScalarKind.INTEGER),
        NormalizedCell(value=2.5, scalar_kind=ScalarKind.NUMBER),
        NormalizedCell(value="7", scalar_kind=ScalarKind.STRING),
        NormalizedCell(value=None, scalar_kind=ScalarKind.NULL),
    )


def test_non_finite_and_unsupported_cells_have_stable_reasons() -> None:
    assert normalize_excel_cell(float("nan")) == CellFailure(
        "non_finite_number"
    )
    assert normalize_excel_cell(float("inf")) == CellFailure(
        "non_finite_number"
    )
    assert normalize_excel_cell([1, float("-inf")]) == CellFailure(
        "non_finite_number"
    )
    assert normalize_excel_cell(b"binary") == CellFailure(
        "unsupported_cell_value"
    )


def test_introduced_normalization_failure_exposes_no_partial_rows() -> None:
    arguments = SearchCompaniesArguments(company_query="회사")
    source = ExcelSourceDataset(
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        arguments=arguments,
        context_columns=("company_query",),
        source_columns=("valid", "invalid"),
        rows=(
            PendingExcelRow(
                (("company_query", "회사"),),
                (("valid", "would be partial"), ("invalid", b"binary")),
            ),
        ),
        warnings=(),
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.SEARCH_COMPANIES,
            source_rows=1,
            normalized_rows=1,
        ),
    )

    result = normalize_excel_source(source)

    assert not result.ok
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.VALIDATION_FAILED
    assert result.error.retryable is False
    assert result.error.details == {"reason": "unsupported_cell_value"}
