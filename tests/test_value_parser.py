import pytest

from dart_crawler.value_parser import parse_cell_value


@pytest.mark.parametrize(
    ("formula_text", "expected"),
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+SUM(A1:A2)", "'+SUM(A1:A2)"),
        ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
        ("-SUM(A1:A2)", "'-SUM(A1:A2)"),
    ],
)
def test_parse_cell_value_neutralizes_all_formula_prefixes(
    formula_text: str,
    expected: str,
) -> None:
    assert parse_cell_value(formula_text) == expected
