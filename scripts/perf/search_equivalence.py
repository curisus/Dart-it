"""Real-data equivalence of the cached-directory company ranking.

Downloads the OpenDART company directory once (one request; the API key comes
from ``load_settings`` and is never printed or written), builds deterministic
queries from the real company names and checks, for every query, that the new
top-20 (``_top_ranked`` over the cached index) equals the reference that
``search()`` used before the cache: ``sorted(_rank_entry(...) for every
entry, key=(-score, company_name))[:20]`` - same entries in the same order with
the same scores and confidences.

Run from the repo root: ``uv run python scripts/perf/search_equivalence.py``.
The reference ranking takes seconds per query, so queries are spread over
worker processes; each worker times both rankings of a query back to back.
Exit status: 0 no mismatch, 1 at least one mismatch, 2 setup failure.
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dart_crawler.company_directory import (
    CompanyDirectoryIndex,
    _parse_company_archive,
    build_company_directory_index,
)
from dart_crawler.company_name_matching import (
    _BRAND_TOKEN_PAIRS,
    CompanyCode,
    _letter_reading,
    _query_readings,
)
from dart_crawler.company_search import _rank_entry, _SearchMatch, _top_ranked
from dart_crawler.dart_api import DartApi
from dart_crawler.http_client import HttpxClient
from dart_crawler.settings import load_settings

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_SEED: Final = 20260928
DEFAULT_QUERIES: Final = 2_100
TOP: Final = 20
EXIT_MISMATCH: Final = 1
EXIT_SETUP: Final = 2
_SHOWN_MISMATCHES: Final = 10
_NS_PER_MS: Final = 1_000_000

type Row = tuple[str, str, str | None, float, str]


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    kind: str
    query: str
    same: bool
    old_ms: float
    new_ms: float
    expected: tuple[Row, ...]
    actual: tuple[Row, ...]


# ---------------------------------------------------------------- queries


def _typo(rng: random.Random, name: str, alphabet: str) -> str:
    position = rng.randrange(len(name))
    edit = rng.randrange(4)
    if edit == 0 and len(name) > 1:
        return name[:position] + name[position + 1 :]
    if edit == 1:
        return name[:position] + rng.choice(alphabet) + name[position + 1 :]
    if edit == 2 and position + 1 < len(name):
        return (
            name[:position] + name[position + 1] + name[position] + name[position + 2 :]
        )
    return name[:position] + rng.choice(alphabet) + name[position:]


def _latin_brand(name: str) -> str | None:
    for latin, hangul in _BRAND_TOKEN_PAIRS:
        if hangul in name:
            return name.replace(hangul, latin, 1)
    return None


def _spacing_variant(rng: random.Random, name: str) -> str:
    position = rng.randrange(len(name) + 1)
    spaced = name[:position] + " " + name[position:]
    return spaced.upper() if rng.random() < 0.5 else spaced.lower()


_KNOWN_QUERIES: Final = (
    "삼성전자",
    "SK하이닉스",
    "에스케이하이닉스",
    "sk하이닉스",
    "KB금융",
    "케이비금융지주",
    "NAVER",
    "네이버",
    "포스코홀딩스",
    "posco홀딩스",
    "삼성바이오로직스",
    "현대차",
    "현대자동차",
    "LG에너지솔루션",
    "엘지에너지솔루션",
    "셀트리온",
    "카카오",
    "에스케이",
    "삼",
    "a",
)


def build_queries(
    entries: Sequence[CompanyCode], total: int, seed: int
) -> list[tuple[str, str]]:
    """(kind, query) pairs, deterministic for one directory and seed."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not secrets
    names = [entry.company_name for entry in entries]
    alphabet = "".join(sorted({char for name in names[:5_000] for char in name}))
    stock_codes = [entry.stock_code for entry in entries if entry.stock_code]
    latin_names = [
        name for name in names if any(c.isascii() and c.isalpha() for c in name)
    ]
    brand_names = [name for name in names if _latin_brand(name) is not None]
    queries: dict[str, str] = dict.fromkeys(_KNOWN_QUERIES, "known")
    share = max(1, total // 9)

    def add(kind: str, query: str) -> None:
        if query.strip() and query not in queries:
            queries[query] = kind

    rounds = 0
    while len(queries) < total and rounds < 50:
        rounds += 1
        for _ in range(share):
            name = rng.choice(names)
            add("full_name", name)
            add("prefix", name[: rng.randint(1, max(1, len(name) - 1))])
            start = rng.randrange(len(name))
            add("substring", name[start : start + rng.randint(2, 4)])
            add("stock_code", rng.choice(stock_codes))
            add("corp_code", rng.choice(entries).corp_code)
            add("typo", _typo(rng, rng.choice(names), alphabet))
            add("letter_reading", _letter_reading(rng.choice(latin_names)))
            brand = _latin_brand(rng.choice(brand_names))
            if brand is not None:
                add("latin_brand", brand)
            add("spacing_case", _spacing_variant(rng, rng.choice(names)))
    return [(kind, query) for query, kind in list(queries.items())[:total]]


# ---------------------------------------------------------------- workers

_WORKER_INDEX: CompanyDirectoryIndex | None = None


def _load_index(archive: bytes) -> CompanyDirectoryIndex:
    parsed = _parse_company_archive(archive)
    if not parsed.ok or parsed.data is None:
        msg = "company directory could not be parsed"
        raise RuntimeError(msg)
    return build_company_directory_index(parsed.data)


def _init_worker(archive: bytes) -> None:
    global _WORKER_INDEX  # noqa: PLW0603 - one index per worker process
    _WORKER_INDEX = _load_index(archive)


def _row(match: _SearchMatch) -> Row:
    entry = match.entry
    return (
        entry.corp_code,
        entry.company_name,
        entry.stock_code,
        match.score,
        match.confidence.value,
    )


def _compare(index: CompanyDirectoryIndex, kind: str, query: str) -> QueryOutcome:
    readings = _query_readings(query)
    started = time.perf_counter_ns()
    expected = sorted(
        (_rank_entry(entry, readings) for entry in index.entries),
        key=lambda match: (-match.score, match.entry.company_name),
    )[:TOP]
    old_ns = time.perf_counter_ns() - started
    started = time.perf_counter_ns()
    actual = _top_ranked(index, readings)
    new_ns = time.perf_counter_ns() - started
    # Identity, not equality: two directory rows may share every field.
    same = [id(match.entry) for match in actual] == [
        id(match.entry) for match in expected
    ] and [_row(match) for match in actual] == [_row(match) for match in expected]
    return QueryOutcome(
        kind=kind,
        query=query,
        same=same,
        old_ms=old_ns / _NS_PER_MS,
        new_ms=new_ns / _NS_PER_MS,
        expected=tuple(_row(match) for match in expected),
        actual=tuple(_row(match) for match in actual),
    )


def _compare_chunk(chunk: Sequence[tuple[str, str]]) -> list[QueryOutcome]:
    index = _WORKER_INDEX
    if index is None:
        msg = "worker index not initialised"
        raise RuntimeError(msg)
    return [_compare(index, kind, query) for kind, query in chunk]


# ---------------------------------------------------------------- main


def _download_archive() -> bytes | str:
    settings = load_settings(process_dir=REPO_ROOT)
    if not settings.ok or settings.data is None:
        code = settings.error.code if settings.error is not None else "unknown"
        return f"settings unavailable ({code})"
    with HttpxClient() as client:
        archive = DartApi(
            client, api_key=settings.data.api_key.get_secret_value()
        ).download_company_codes()
    if not archive.ok or archive.data is None:
        code = archive.error.code if archive.error is not None else "unknown"
        return f"company directory download failed ({code})"
    return archive.data


def _summary(label: str, values: Sequence[float]) -> str:
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    return (
        f"{label}: median {statistics.median(ordered):.1f} ms, p90 {p90:.1f} ms, "
        f"total {sum(ordered) / 1000:.1f} s"
    )


def _print_mismatch(outcome: QueryOutcome) -> None:
    print(f"MISMATCH [{outcome.kind}] {outcome.query!r}")
    for rank, (expected, actual) in enumerate(
        zip(outcome.expected, outcome.actual, strict=False), start=1
    ):
        marker = "  " if expected == actual else "!!"
        print(f"  {marker} #{rank:02d} expected {expected} actual {actual}")
    if len(outcome.expected) != len(outcome.actual):
        print(
            f"  lengths: expected {len(outcome.expected)} actual {len(outcome.actual)}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    parser.add_argument("--queries", type=int, default=DEFAULT_QUERIES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--workers", type=int, default=max(1, min(12, (os.cpu_count() or 2) - 2))
    )
    namespace = parser.parse_args(argv)

    started = time.perf_counter()
    archive = _download_archive()
    if isinstance(archive, str):
        print(f"error: {archive}", file=sys.stderr)
        return EXIT_SETUP
    download_s = time.perf_counter() - started
    started = time.perf_counter()
    index = _load_index(archive)
    load_s = time.perf_counter() - started
    queries = build_queries(index.entries, namespace.queries, namespace.seed)
    print(
        f"directory: {len(index.entries)} companies, {len(archive)} bytes "
        f"(download {download_s:.1f} s, parse+index {load_s:.1f} s); "
        f"OpenDART requests: 1"
    )
    print(
        f"queries: {len(queries)} (seed {namespace.seed}), workers {namespace.workers}"
    )
    for kind, count in sorted(Counter(kind for kind, _ in queries).items()):
        print(f"  {kind}: {count}")

    chunks = [
        queries[offset :: namespace.workers * 4]
        for offset in range(namespace.workers * 4)
    ]
    outcomes: list[QueryOutcome] = []
    started = time.perf_counter()
    with ProcessPoolExecutor(
        max_workers=namespace.workers, initializer=_init_worker, initargs=(archive,)
    ) as pool:
        for chunk_outcomes in pool.map(_compare_chunk, chunks):
            outcomes.extend(chunk_outcomes)
    wall_s = time.perf_counter() - started

    mismatches = [outcome for outcome in outcomes if not outcome.same]
    for outcome in mismatches[:_SHOWN_MISMATCHES]:
        _print_mismatch(outcome)
    old = [outcome.old_ms for outcome in outcomes]
    new = [outcome.new_ms for outcome in outcomes]
    print(_summary("old rank (full sort)", old))
    print(_summary("new rank (cached top-k)", new))
    print(
        f"median speedup x{statistics.median(old) / statistics.median(new):.1f}; "
        f"wall {wall_s:.0f} s"
    )
    print(f"compared {len(outcomes)} queries: {len(mismatches)} mismatches")
    return EXIT_MISMATCH if mismatches or len(outcomes) != len(queries) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
