from dart_crawler.domain import Company, Filing, Market, ReportKind, ReportPeriod


def test_company_keeps_market_and_rank_as_typed_values() -> None:
    company = Company(
        company_name="Sample Company",
        corp_code="00126380",
        stock_code="005930",
        market=Market.KOSPI,
        ranking=1,
    )

    assert company.market is Market.KOSPI
    assert company.ranking == 1


def test_filing_keeps_corrected_receipts_in_one_chain() -> None:
    filing = Filing(
        corp_code="00126380",
        company_name="Sample Company",
        report_kind=ReportKind.AUDIT,
        report_period=ReportPeriod.FY,
        fiscal_year=2025,
        report_name="사업보고서",
        rcept_no="20260310002820",
        receipt_date="20260310",
        correction_chain=("20260310002820", "20260312000123"),
    )

    assert filing.report_period is ReportPeriod.FY
    assert filing.correction_chain[-1] == "20260312000123"
