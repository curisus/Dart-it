from dataclasses import dataclass
from io import BytesIO
from zipfile import ZipFile

import pytest

from dart_crawler.api_models import DartListRow
from dart_crawler.company_search import CompanySearchService
from dart_crawler.domain import Company, MatchConfidence
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


def _brand_archive() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00126383</corp_code><corp_name>POSCO홀딩스</corp_name><stock_code>005932</stock_code></list>
      <list><corp_code>00126384</corp_code><corp_name>제이스코홀딩스</corp_name><stock_code>005933</stock_code></list>
      <list><corp_code>00126385</corp_code><corp_name>에스코홀딩스</corp_name><stock_code>005934</stock_code></list>
    </result>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def _brand_token_boundary_archive() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00126386</corp_code><corp_name>에스케이하이닉스</corp_name><stock_code>000660</stock_code></list>
      <list><corp_code>00126387</corp_code><corp_name>RISK인베스트먼트</corp_name><stock_code></stock_code></list>
    </result>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def _exact_alias_archive() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00126388</corp_code><corp_name>에스케이</corp_name><stock_code></stock_code></list>
      <list><corp_code>00126389</corp_code><corp_name>SK</corp_name><stock_code></stock_code></list>
    </result>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def _compact_brand_archive() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00139889</corp_code><corp_name>SKC</corp_name><stock_code>011790</stock_code></list>
      <list><corp_code>00878517</corp_code><corp_name>에스케이씨에스</corp_name><stock_code>224020</stock_code></list>
    </result>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def _letter_reading_archive() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00139890</corp_code><corp_name>ISC</corp_name><stock_code>095340</stock_code></list>
      <list><corp_code>00139889</corp_code><corp_name>SKC</corp_name><stock_code>011790</stock_code></list>
      <list><corp_code>00139891</corp_code><corp_name>씨아이에스</corp_name><stock_code>222080</stock_code></list>
      <list><corp_code>00878517</corp_code><corp_name>에스케이씨에스</corp_name><stock_code>224020</stock_code></list>
    </result>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


@dataclass(frozen=True, slots=True)
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
    assert result.error is None
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


def test_exact_brand_name_outranks_similar_names() -> None:
    service = CompanySearchService(FakeSource(_brand_archive()))

    result = service.search("포스코홀딩스", "audit")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == "POSCO홀딩스"


def test_exact_company_name_outranks_alias() -> None:
    # Given
    service = CompanySearchService(FakeSource(_exact_alias_archive()))

    # When
    result = service.search("에스케이", "audit")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == "에스케이"
    assert result.data[0].ranking == 1
    assert result.data[0].match_confidence is MatchConfidence.EXACT
    assert result.data[1].match_confidence is MatchConfidence.ALIAS


def test_brand_match_reports_match_confidence() -> None:
    service = CompanySearchService(FakeSource(_brand_archive()))

    result = service.search("포스코홀딩스", "audit")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].match_confidence is MatchConfidence.ALIAS
    assert all(
        company.match_confidence is MatchConfidence.SIMILAR
        for company in result.data[1:]
    )


def test_brand_match_keeps_similar_names_ranked_by_similarity() -> None:
    service = CompanySearchService(FakeSource(_brand_archive()))

    result = service.search("포스코홀딩스", "audit")

    assert result.ok is True
    assert result.data is not None
    assert [company.company_name for company in result.data] == [
        "POSCO홀딩스",
        "에스코홀딩스",
        "제이스코홀딩스",
    ]


def test_latin_brand_query_matches_hangul_company_name() -> None:
    service = CompanySearchService(FakeSource(_brand_archive()))

    result = service.search("posco홀딩스", "audit")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == "POSCO홀딩스"


@pytest.mark.parametrize(
    ("query", "expected_name", "expected_confidence"),
    [
        ("아이에스씨", "ISC", MatchConfidence.ALIAS),
        ("에스케이씨", "SKC", MatchConfidence.ALIAS),
        ("SKC", "SKC", MatchConfidence.EXACT),
    ],
)
def test_letter_reading_exact_match_ranks_company_first(
    query: str,
    expected_name: str,
    expected_confidence: MatchConfidence,
) -> None:
    # Given
    service = CompanySearchService(FakeSource(_letter_reading_archive()))

    # When
    result = service.search(query, "audit")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == expected_name
    assert result.data[0].ranking == 1
    assert result.data[0].match_confidence is expected_confidence


def test_brand_token_inside_latin_word_is_not_an_alias_match() -> None:
    service = CompanySearchService(FakeSource(_brand_token_boundary_archive()))

    result = service.search("에스케이", "audit")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == "에스케이하이닉스"
    risk_company = next(
        company
        for company in result.data
        if company.company_name == "RISK인베스트먼트"
    )
    assert risk_company.match_confidence is MatchConfidence.SIMILAR


def test_korean_compact_brand_query_ranks_latin_alias_first() -> None:
    # Given
    service = CompanySearchService(FakeSource(_compact_brand_archive()))

    # When
    result = service.search("에스케이씨", "audit")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [company.company_name for company in result.data] == [
        "SKC",
        "에스케이씨에스",
    ]
    assert result.data[0].ranking == 1
    assert result.data[0].match_confidence is MatchConfidence.ALIAS
    assert result.data[1].match_confidence is MatchConfidence.PREFIX


def test_latin_compact_brand_query_keeps_exact_company_first() -> None:
    # Given
    service = CompanySearchService(FakeSource(_compact_brand_archive()))

    # When
    result = service.search("SKC", "audit")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data[0].company_name == "SKC"
    assert result.data[0].ranking == 1
    assert result.data[0].match_confidence is MatchConfidence.EXACT


def test_company_search_failure_has_error_only_result() -> None:
    service = CompanySearchService(FakeSource(_company_archive()))

    result = service.search("", "audit")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None


def test_company_serialization_preserves_match_confidence() -> None:
    service = CompanySearchService(FakeSource(_company_archive()))

    result = service.search("005930", "audit")
    serialized = result.model_dump_json()
    restored = Result[tuple[Company, ...]].model_validate_json(serialized)

    assert restored.ok is True
    assert restored.data is not None
    assert restored.error is None
    assert restored.data[0].match_confidence is MatchConfidence.EXACT
