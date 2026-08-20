from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from dart_crawler.domain import MatchConfidence


@dataclass(frozen=True, slots=True)
class CompanyCode:
    """One row from the CORPCODE.xml archive."""

    corp_code: str
    company_name: str
    stock_code: str | None


@dataclass(frozen=True, slots=True)
class _QueryReadings:
    normalized: str
    brand: str
    letter: str


@dataclass(frozen=True, slots=True)
class _CompanyNameMatch:
    score: float
    confidence: MatchConfidence


_BRAND_TOKEN_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("posco", "포스코"),
    ("sk", "에스케이"),
    ("skc", "에스케이씨"),
    ("lg", "엘지"),
    ("kt", "케이티"),
    ("ktcs", "케이티씨에스"),
    ("ktis", "케이티아이에스"),
    ("cj", "씨제이"),
    ("gs", "지에스"),
    ("hd", "에이치디"),
    ("hdc", "에이치디씨"),
    ("kb", "케이비"),
    ("kbg", "케이비지"),
    ("kbi", "케이비아이"),
    ("nh", "엔에이치"),
    ("nhn", "엔에이치엔"),
    ("bnk", "비엔케이"),
    ("dgb", "디지비"),
    ("jb", "제이비"),
    ("hmm", "에이치엠엠"),
    ("ls", "엘에스"),
    ("db", "디비"),
    ("dl", "디엘"),
    ("ok", "오케이"),
    ("sc", "에스씨"),
    ("sci", "에스씨아이"),
    ("scl", "에스씨엘"),
)
_BRAND_TOKEN_MAP: Final[dict[str, str]] = dict(_BRAND_TOKEN_PAIRS)
_BRAND_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(latin for latin, _ in _BRAND_TOKEN_PAIRS)
    + r")(?![A-Za-z0-9])"
)
_LETTER_READINGS: Final[dict[str, str]] = {
    "a": "에이",
    "b": "비",
    "c": "씨",
    "d": "디",
    "e": "이",
    "f": "에프",
    "g": "지",
    "h": "에이치",
    "i": "아이",
    "j": "제이",
    "k": "케이",
    "l": "엘",
    "m": "엠",
    "n": "엔",
    "o": "오",
    "p": "피",
    "q": "큐",
    "r": "알",
    "s": "에스",
    "t": "티",
    "u": "유",
    "v": "브이",
    "w": "더블유",
    "x": "엑스",
    "y": "와이",
    "z": "지",
}
_LETTER_RUN_READING_OVERRIDES: Final[dict[str, str]] = {
    "cjcgv": "씨제이씨지비",
}
_ASCII_LETTER_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]+")


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())


def _canonical_key(value: str) -> str:
    boundary_preserving = _BRAND_TOKEN_PATTERN.sub(
        lambda match: _BRAND_TOKEN_MAP[match.group()],
        value.casefold(),
    )
    return "".join(boundary_preserving.split())


def _letter_reading(value: str) -> str:
    return _ASCII_LETTER_RUN_PATTERN.sub(
        lambda match: _LETTER_RUN_READING_OVERRIDES.get(
            match.group(),
            "".join(_LETTER_READINGS[letter] for letter in match.group()),
        ),
        _normalize(value),
    )


def _query_readings(value: str) -> _QueryReadings:
    return _QueryReadings(
        normalized=_normalize(value),
        brand=_canonical_key(value),
        letter=_letter_reading(value),
    )


def _rank_company(
    entry: CompanyCode,
    query: _QueryReadings,
) -> _CompanyNameMatch:
    name = _normalize(entry.company_name)
    stock = entry.stock_code or ""
    if query.normalized == stock or query.normalized == entry.corp_code:
        return _CompanyNameMatch(1_000.0, MatchConfidence.EXACT)
    if query.normalized == name:
        return _CompanyNameMatch(950.0, MatchConfidence.EXACT)
    if name.startswith(query.normalized):
        return _CompanyNameMatch(800.0, MatchConfidence.PREFIX)
    if query.normalized in name:
        return _CompanyNameMatch(700.0, MatchConfidence.CONTAINS)
    letter_name = _letter_reading(entry.company_name)
    # Letter readings must stay exact-only: contains would make 에스케이 a false
    # alias of RISK인베스트먼트 (알아이에스케이인베스트먼트).
    if (
        query.letter == name
        or query.normalized == letter_name
        or query.letter == letter_name
    ):
        return _CompanyNameMatch(900.0, MatchConfidence.ALIAS)
    canonical_name = _canonical_key(entry.company_name)
    if query.brand == canonical_name:
        return _CompanyNameMatch(900.0, MatchConfidence.ALIAS)
    if canonical_name.startswith(query.brand):
        return _CompanyNameMatch(850.0, MatchConfidence.ALIAS)
    if query.brand in canonical_name:
        return _CompanyNameMatch(825.0, MatchConfidence.ALIAS)
    score = SequenceMatcher(None, query.brand, canonical_name).ratio() * 100.0
    return _CompanyNameMatch(score, MatchConfidence.SIMILAR)
