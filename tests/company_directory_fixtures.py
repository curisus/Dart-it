"""Deterministic synthetic company directories and queries for ranking tests."""

import random
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZipFile

from dart_crawler.company_name_matching import CompanyCode

_BRANDS = (
    "삼성",
    "현대",
    "에스케이",
    "SK",
    "엘지",
    "LG",
    "KB",
    "케이비",
    "POSCO",
    "포스코",
    "CJ",
    "씨제이",
    "GS",
    "HD",
    "NH",
    "SKC",
    "ISC",
    "KT",
    "한화",
    "롯데",
    "대한",
    "동화",
    "RISK",
)
_SUFFIXES = (
    "전자",
    "전자서비스",
    "전자판매",
    "하이닉스",
    "화학",
    "건설",
    "홀딩스",
    "금융지주",
    "바이오로직스",
    "생명",
    "증권",
    "인베스트먼트",
    "에너지",
    "제약",
    "",
)
_SYLLABLES = "가나다라마바사아자차카타파하고노도로모보소오조초코토포호강산전기"
_LATIN = "abcdefghijklmnopqrstuvwxyz"


def _random_word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(1, 4)))


def _random_name(rng: random.Random) -> str:
    kind = rng.random()
    if kind < 0.45:
        name = rng.choice(_BRANDS) + rng.choice(_SUFFIXES)
    elif kind < 0.75:
        name = _random_word(rng) + rng.choice(_SUFFIXES)
    elif kind < 0.85:
        name = "".join(rng.choice(_LATIN) for _ in range(rng.randint(2, 4))).upper()
    else:
        name = rng.choice(_BRANDS) + " " + _random_word(rng)
    return name or _random_word(rng)


def synthetic_entries(count: int, seed: int) -> tuple[CompanyCode, ...]:
    """Names with many duplicates, shared prefixes, aliases and near-misses."""
    rng = random.Random(seed)  # noqa: S311 - reproducible test data, not secrets
    entries: list[CompanyCode] = []
    for index in range(count):
        if entries and rng.random() < 0.08:
            # An exact duplicate name makes (score, name) ties that only the
            # archive order can break.
            name = rng.choice(entries).company_name
        else:
            name = _random_name(rng)
        stock_code = f"{rng.randrange(1_000_000):06d}" if rng.random() < 0.3 else None
        entries.append(CompanyCode(f"{10_000_000 + index:08d}", name, stock_code))
    return tuple(entries)


def _typo(rng: random.Random, name: str) -> str:
    if len(name) < 2:
        return name + rng.choice(_SYLLABLES)
    position = rng.randrange(len(name))
    edit = rng.randrange(3)
    if edit == 0:
        return name[:position] + name[position + 1 :]
    if edit == 1:
        return name[:position] + rng.choice(_SYLLABLES) + name[position + 1 :]
    return name[:position] + rng.choice(_SYLLABLES) + name[position:]


def synthetic_queries(
    entries: tuple[CompanyCode, ...],
    per_kind: int,
    seed: int,
) -> tuple[str, ...]:
    """Queries of every ranking tier, including ones no fixed tier matches."""
    rng = random.Random(seed)  # noqa: S311 - reproducible test data, not secrets
    names = [entry.company_name for entry in entries]
    stock_codes = [entry.stock_code for entry in entries if entry.stock_code]
    queries: list[str] = []
    for _ in range(per_kind):
        name = rng.choice(names)
        cut = rng.randint(1, max(1, len(name) - 1))
        start = rng.randrange(len(name))
        queries.extend(
            (
                rng.choice(entries).corp_code,
                rng.choice(stock_codes),
                name,
                name[:cut],
                name[start : start + rng.randint(1, 3)],
                _typo(rng, name),
                # no fixed tier: letters and syllables absent from every name
                "".join(rng.choice("QXZ") for _ in range(rng.randint(2, 4))),
                "훟" + _random_word(rng),
            )
        )
    queries.extend(
        (
            "에스케이",
            "sk하이닉스",
            "에스케이하이닉스",
            "posco홀딩스",
            "포스코홀딩스",
            "kb금융지주",
            "케이비금융",
            "아이에스씨",
            "에스케이씨",
            "SKC",
            "cj",
            "삼성",
            "삼",
            "전자",
            "a",
            "Risk",
            " 삼성 전자 ",
        )
    )
    return tuple(queries)


def directory_archive(entries: tuple[CompanyCode, ...]) -> bytes:
    """A corpCode ZIP whose CORPCODE.xml parses back into the entries."""
    rows = "".join(
        "<list>"
        f"<corp_code>{entry.corp_code}</corp_code>"
        f"<corp_name>{escape(entry.company_name)}</corp_name>"
        f"<stock_code>{entry.stock_code or ''}</stock_code>"
        "</list>"
        for entry in entries
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "CORPCODE.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><result>{rows}</result>',
        )
    return buffer.getvalue()
