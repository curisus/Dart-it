from dataclasses import dataclass

from dart_crawler.api_models import DartListRow
from dart_crawler.domain import ReportPeriod
from dart_crawler.filing_service import FilingService, validate_report_kind
from dart_crawler.result import ErrorCode, Result


def _row(
    report_name: str,
    rcept_no: str,
    receipt_date: str,
    *,
    rm: str = "",
) -> DartListRow:
    return DartListRow(
        corp_cls="Y",
        corp_name="Sample",
        corp_code="00126380",
        stock_code="005930",
        report_nm=report_name,
        rcept_no=rcept_no,
        rcept_dt=receipt_date,
        rm=rm,
    )


@dataclass
class FakeDisclosureSource:
    rows: tuple[DartListRow, ...]

    def list_disclosures(
        self,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        return Result.success(self.rows)


def test_audit_correction_uses_latest_receipt_without_extra_year() -> None:
    service = FilingService(
        FakeDisclosureSource(
            (
                _row("사업보고서 (2025.12)", "20260310000001", "20260310"),
                _row(
                    "[기재정정] 사업보고서 (2025.12)",
                    "20260312000002",
                    "20260312",
                    rm="정",
                ),
                _row("사업보고서 (2024.12)", "20250310000003", "20250310"),
                _row(
                    "[기재정정] 사업보고서 (2023.12)",
                    "20240311000005",
                    "20240311",
                    rm="철회",
                ),
                _row(
                    "사업보고서 (2023.12)",
                    "20240310000004",
                    "20240310",
                ),
            )
        )
    )

    result = service.list("00126380", "Sample", "audit")

    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 3
    assert result.data[0].rcept_no == "20260312000002"
    assert result.data[0].correction_chain == (
        "20260310000001",
        "20260312000002",
    )
    assert result.data[0].report_period is ReportPeriod.FY
    assert result.data[1].rcept_no == "20250310000003"
    assert result.data[2].rcept_no == "20240310000004"
    assert result.data[2].correction_chain == (
        "20240310000004",
        "20240311000005",
    )


def test_quarterly_filing_keeps_first_and_third_quarters_separate() -> None:
    service = FilingService(
        FakeDisclosureSource(
            (
                _row("분기보고서 (2025.03)", "20250501000001", "20250501"),
                _row("분기보고서 (2025.09)", "20251101000002", "20251101"),
                _row("분기보고서 (2024.03)", "20240501000003", "20240501"),
            )
        )
    )

    result = service.list("00126380", "Sample", "quarterly_review")

    assert result.ok is True
    assert result.data is not None
    assert [item.report_period for item in result.data] == [
        ReportPeriod.FIRST_QUARTER,
        ReportPeriod.THIRD_QUARTER,
        ReportPeriod.FIRST_QUARTER,
    ]


def test_unsupported_report_kind_names_the_supported_ones() -> None:
    """Every sibling tool answers an unknown enum with its supported values."""
    service = FilingService(_RejectingFilingSource())

    result = service.list("00126380", "삼성전자", "review")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    supported = result.error.details["supported_report_kinds"]
    assert supported == [
        {"key": "audit", "label": "감사보고서"},
        {"key": "half_year_review", "label": "반기검토보고서"},
        {"key": "quarterly_review", "label": "분기검토보고서"},
    ]
    assert result.next_action is not None


class _RejectingFilingSource:
    def list_disclosures(
        self,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        raise AssertionError((corp_code, report_detail_type))


def test_report_kind_is_validated_before_any_lookup() -> None:
    """A caller resolving the company first would report "회사 없음" instead."""
    violation = validate_report_kind("review")

    assert violation is not None
    assert violation.error.code is ErrorCode.INVALID_INPUT
    assert "supported_report_kinds" in violation.error.details
    assert validate_report_kind("audit") is None
