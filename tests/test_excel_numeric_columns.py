from dart_crawler.excel_numeric_columns import (
    coerce_numeric_columns,
    numeric_column_formats,
)
from dart_crawler.excel_page_models import ExcelRow


def _rows(*values: tuple[str, str]) -> tuple[ExcelRow, ...]:
    return tuple(
        {"corp_code": code, "thstrm_amount": amount} for code, amount in values
    )


def test_amount_column_of_plain_digits_becomes_numbers() -> None:
    columns = ("corp_code", "thstrm_amount")
    rows = _rows(("00126380", "566942110000000"), ("00126380", "358902051000000"))

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ("thstrm_amount",)
    assert [row["thstrm_amount"] for row in coerced] == [
        566942110000000,
        358902051000000,
    ]


def test_identifier_columns_stay_text_even_when_every_value_is_numeric() -> None:
    """corp_code loses its leading zeros the moment it becomes a number."""
    columns = ("corp_code", "thstrm_amount")
    rows = _rows(("00126380", "1000"))

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert "corp_code" not in numeric
    assert coerced[0]["corp_code"] == "00126380"


def test_thousands_separators_and_bracketed_negatives_are_read() -> None:
    columns = ("thstrm_amount",)
    rows: tuple[ExcelRow, ...] = (
        {"thstrm_amount": "1,234,567"},
        {"thstrm_amount": "(112,071)"},
    )

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ("thstrm_amount",)
    assert [row["thstrm_amount"] for row in coerced] == [1234567, -112071]


def test_a_column_holding_one_placeholder_stays_text() -> None:
    columns = ("thstrm_amount",)
    rows: tuple[ExcelRow, ...] = (
        {"thstrm_amount": "1,234,567"},
        {"thstrm_amount": "-"},
    )

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ()
    assert [row["thstrm_amount"] for row in coerced] == ["1,234,567", "-"]


def test_blank_values_neither_disqualify_a_column_nor_become_numbers() -> None:
    columns = ("thstrm_amount",)
    rows: tuple[ExcelRow, ...] = (
        {"thstrm_amount": "1,000"},
        {"thstrm_amount": ""},
    )

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ("thstrm_amount",)
    assert [row["thstrm_amount"] for row in coerced] == [1000, ""]


def test_a_column_of_only_blanks_is_not_numeric() -> None:
    columns = ("thstrm_amount",)
    rows: tuple[ExcelRow, ...] = ({"thstrm_amount": ""},)

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ()
    assert coerced == rows


def test_a_renamed_source_column_is_still_recognized() -> None:
    """Colliding source columns are republished as source_<name>."""
    columns = ("source_thstrm_amount",)
    rows: tuple[ExcelRow, ...] = ({"source_thstrm_amount": "1,000"},)

    _coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ("source_thstrm_amount",)


def test_already_numeric_columns_are_left_alone() -> None:
    columns = ("bsns_year",)
    rows: tuple[ExcelRow, ...] = ({"bsns_year": 2025},)

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ()
    assert coerced[0]["bsns_year"] == 2025


def test_indicator_values_keep_their_decimal_places() -> None:
    columns = ("idx_val",)
    rows: tuple[ExcelRow, ...] = (
        {"idx_val": "12.34"},
        {"idx_val": "5.6"},
    )

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric == ("idx_val",)
    assert coerced[0]["idx_val"] == 12.34
    assert numeric_column_formats(numeric, coerced) == {"idx_val": "#,##0.00"}


def test_whole_amount_columns_display_thousands_separators() -> None:
    columns = ("thstrm_amount",)
    rows: tuple[ExcelRow, ...] = ({"thstrm_amount": "1000"},)

    coerced, numeric = coerce_numeric_columns(columns, rows)

    assert numeric_column_formats(numeric, coerced) == {"thstrm_amount": "#,##0"}
