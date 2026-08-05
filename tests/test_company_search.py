from dataclasses import dataclass
from io import BytesIO
from zipfile import ZipFile

from dart_crawler.api_models import DartListRow
from dart_crawler.company_search import CompanySearchService
from dart_crawler.result import Result


def _company_archive() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00126380</corp_code><corp_name>Sample Holdings</corp_name><stock_code>005930</stock_code></list>
      <list><corp_code>00126381</corp_code><corp_name>Sample Bio</corp_name><stock_code>005931</stock_code></list>
      <list><corp_code>00126382</corp_code><corp_name>Other Company</corp_name><stock_code></stock_code></list>
    </result>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


@dataclass
class FakeSource:
    archive: bytes

    def download_company_codes(self) -> Result[bytes]:
        return Result.success(self.archive)

    def list_disclosures(
        self,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        return Result.success(
            (
                DartListRow(
                    corp_cls="Y",
                    corp_name="Sample Holdings",
                    corp_code=corp_code,
                    stock_code="005930",
                    report_nm="사업보고서",
                    rcept_no="20260310002820",
                    rcept_dt="20260310",
                    rm="",
                ),
            )
        )


def test_search_prioritizes_exact_stock_code_and_returns_market() -> None:
    service = CompanySearchService(FakeSource(_company_archive()))

    result = service.search("005930", "audit")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == "Sample Holdings"
    assert result.data[0].market.value == "Y"
    assert result.data[0].ranking == 1


def test_search_returns_at_most_five_ranked_companies() -> None:
    service = CompanySearchService(FakeSource(_company_archive()))

    result = service.search("Sample", "audit")

    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 3
    assert [company.ranking for company in result.data] == [1, 2, 3]
