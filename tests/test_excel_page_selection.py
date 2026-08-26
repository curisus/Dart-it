from typing import TypeVar

from pydantic import SecretBytes

from dart_crawler.excel_cursor import (
    CursorBinding,
    CursorSecret,
    decode_excel_cursor,
)
from dart_crawler.excel_page_models import (
    EXCEL_PAGE_BUDGET_BYTES,
    ExcelDataDomain,
)
from dart_crawler.excel_page_selection import (
    ExcelPageSelection,
    NormalizedExcelDataset,
    select_excel_page,
)
from dart_crawler.mcp_wire import (
    WireProfile,
    WireProfileMeasurement,
    WireSizeReport,
    measure_excel_result_wire,
)
from dart_crawler.result import Result, WarningCode, WarningInfo

T = TypeVar("T")
_SECRET = CursorSecret(value=SecretBytes(b"s" * 32))


def _dataset(
    values: tuple[str, ...],
    *,
    column: str = "value",
    warnings: tuple[WarningInfo, ...] = (),
) -> NormalizedExcelDataset:
    return NormalizedExcelDataset(
        columns=(column,),
        rows=tuple({column: value} for value in values),
        source_fingerprint="b" * 64,
        warnings=warnings,
    )


def _selection(
    dataset: NormalizedExcelDataset,
    *,
    page_size: int,
) -> ExcelPageSelection:
    return ExcelPageSelection(
        dataset=dataset,
        domain=ExcelDataDomain.SEARCH_COMPANIES,
        request_fingerprint="a" * 64,
        row_offset=0,
        page_index=0,
        page_size=page_size,
        cursor_secret=_SECRET,
    )


def _failure_reason(result: Result[T]) -> str:
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is False
    assert set(result.error.details) == {"reason"}
    reason = result.error.details["reason"]
    assert isinstance(reason, str)
    return reason


def test_nonterminal_over_budget_uses_greatest_whole_row_prefix() -> None:
    # Given: four normalized rows where one fits but two exceed the full-wire budget.
    dataset = _dataset(tuple("x" * 900_000 for _ in range(4)))

    # When: a three-row nonterminal candidate is selected.
    result = select_excel_page(_selection(dataset, page_size=3))

    # Then: exactly one whole row and a real signed continuation cursor are returned.
    assert result.ok is True
    page = result.data
    assert page is not None
    assert page.returned_rows == 1
    value = page.rows[0]["value"]
    assert isinstance(value, str)
    assert len(value) == 900_000
    assert page.next_cursor is not None
    decoded = decode_excel_cursor(
        page.next_cursor,
        secret=_SECRET,
        binding=CursorBinding(request_fingerprint="a" * 64, page_size=3),
    )
    assert decoded.ok is True
    assert decoded.data is not None
    assert decoded.data.offset == 1
    assert decoded.data.page_index == 1
    report = measure_excel_result_wire(result)
    assert report.fits_strictly(EXCEL_PAGE_BUDGET_BYTES)


def test_terminal_candidate_is_measured_without_a_cursor() -> None:
    # Given: one small row that completes the normalized dataset.
    dataset = _dataset(("terminal",))

    # When: the terminal page is selected.
    result = select_excel_page(_selection(dataset, page_size=1))

    # Then: it has no cursor and every enabled final-wire profile is strictly under budget.
    assert result.ok is True
    page = result.data
    assert page is not None
    assert page.next_cursor is None
    report = measure_excel_result_wire(result)
    assert report.fits_strictly(EXCEL_PAGE_BUDGET_BYTES)


def test_terminal_over_budget_becomes_a_signed_nonterminal_prefix() -> None:
    # Given: two rows whose complete terminal candidate exceeds the wire budget.
    dataset = _dataset(("x" * 900_000, "y" * 900_000))

    # When: terminal-aware selection retries with nonterminal prefixes.
    result = select_excel_page(_selection(dataset, page_size=2))

    # Then: the fitting first row carries a cursor instead of a false terminal response.
    assert result.ok is True
    page = result.data
    assert page is not None
    assert page.returned_rows == 1
    assert page.next_cursor is not None


def test_one_row_over_budget_returns_typed_failure_with_ordered_warnings() -> None:
    # Given: one indivisible row larger than the completed-wire budget.
    warnings = (
        WarningInfo(code=WarningCode.PARTIAL_COLLECTION, message="first"),
        WarningInfo(code=WarningCode.FALLBACK_SOURCE_USED, message="second"),
    )
    dataset = _dataset(("x" * 1_800_000,), warnings=warnings)

    # When: whole-row selection cannot fit any prefix.
    result = select_excel_page(_selection(dataset, page_size=1))

    # Then: the dedicated export-guiding failure preserves all ordered warnings.
    assert _failure_reason(result) == "row_exceeds_page_budget"
    assert result.warnings == warnings
    assert "export_query_excel" in (result.next_action or "")
    assert measure_excel_result_wire(result).fits_strictly(EXCEL_PAGE_BUDGET_BYTES)


def test_schema_only_probe_can_fail_before_row_measurement() -> None:
    # Given: a normalized dataset whose column schema alone exceeds the budget.
    dataset = _dataset((), column="c" * 1_800_000)

    # When: page selection measures the private schema probe first.
    result = select_excel_page(_selection(dataset, page_size=1))

    # Then: it returns the dedicated schema failure with export guidance.
    assert _failure_reason(result) == "dataset_schema_exceeds_page_budget"
    assert "export_query_excel" in (result.next_action or "")


def test_warning_only_overflow_returns_empty_success_without_warnings() -> None:
    # Given: an empty dataset whose schema fits but ordered source warnings do not.
    warnings = (
        WarningInfo(
            code=WarningCode.PARTIAL_COLLECTION,
            message="w" * 1_800_000,
        ),
    )
    dataset = _dataset((), warnings=warnings)

    # When: the completed empty page is selected through the full-wire oracle.
    result = select_excel_page(_selection(dataset, page_size=1))

    # Then: warning overflow is not misclassified as schema overflow.
    assert result.ok is True
    page = result.data
    assert page is not None
    assert page.rows == ()
    assert page.returned_rows == 0
    assert page.next_cursor is None
    assert result.warnings == ()
    assert measure_excel_result_wire(result).fits_strictly(EXCEL_PAGE_BUDGET_BYTES)


def test_wire_budget_is_strictly_less_than_not_equal_to_limit() -> None:
    # Given: profile bodies immediately below and exactly at the fixed byte budget.
    below = WireSizeReport(
        measurements=(
            WireProfileMeasurement(
                profile=WireProfile.LEGACY,
                body=b"x" * (EXCEL_PAGE_BUDGET_BYTES - 1),
            ),
        )
    )
    equal = WireSizeReport(
        measurements=(
            WireProfileMeasurement(
                profile=WireProfile.LEGACY,
                body=b"x" * EXCEL_PAGE_BUDGET_BYTES,
            ),
        )
    )

    # When/Then: only the strictly smaller completed body is accepted.
    assert below.fits_strictly(EXCEL_PAGE_BUDGET_BYTES) is True
    assert equal.fits_strictly(EXCEL_PAGE_BUDGET_BYTES) is False
