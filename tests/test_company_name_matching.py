import pytest

from dart_crawler.company_name_matching import (
    CompanyCode,
    _canonical_key,
    _letter_reading,
    _query_readings,
)
from dart_crawler.company_search import _rank_entry
from dart_crawler.domain import MatchConfidence


@pytest.mark.parametrize(
    ("normalized_value", "expected"),
    [
        ("posco홀딩스", "포스코홀딩스"),
        ("sk하이닉스", "에스케이하이닉스"),
        ("kb금융지주", "케이비금융지주"),
        ("sk", "에스케이"),
        ("skc", "에스케이씨"),
        ("에스케이씨", "에스케이씨"),
        ("ktcs", "케이티씨에스"),
        ("ktis", "케이티아이에스"),
        ("hdc", "에이치디씨"),
        ("kbg", "케이비지"),
        ("kbi메탈", "케이비아이메탈"),
        ("nhn", "엔에이치엔"),
        ("sci평가정보", "에스씨아이평가정보"),
        ("scl사이언스", "에스씨엘사이언스"),
        ("risk", "risk"),
        ("tokyo", "tokyo"),
        ("discovery", "discovery"),
    ],
)
def test_canonical_key_substitutes_only_whole_brand_tokens(
    normalized_value: str,
    expected: str,
) -> None:
    assert _canonical_key(normalized_value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("isc", "아이에스씨"),
        ("skc", "에스케이씨"),
        ("gst", "지에스티"),
        ("cjcgv", "씨제이씨지비"),
        ("risk", "알아이에스케이"),
        ("v", "브이"),
    ],
)
def test_letter_reading_expands_each_ascii_letter(
    value: str,
    expected: str,
) -> None:
    # Given / When
    actual = _letter_reading(value)

    # Then
    assert actual == expected


@pytest.mark.parametrize(
    ("company_name", "query"),
    [
        ("SK Networks", "에스케이 Networks"),
        ("에스케이 Networks", "SK Networks"),
    ],
)
def test_spaced_latin_brand_matches_hangul_alias(
    company_name: str,
    query: str,
) -> None:
    # Given
    entry = CompanyCode("00126388", company_name, None)

    # When
    actual = _rank_entry(entry, _query_readings(query))

    # Then
    assert actual.confidence is MatchConfidence.ALIAS
