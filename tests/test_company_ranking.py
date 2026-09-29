from difflib import SequenceMatcher
from itertools import pairwise
from typing import Final

from dart_crawler.company_directory import build_company_directory_index
from dart_crawler.company_name_matching import (
    _query_readings,
    _rank_company,
    _rank_readings,
    _similar_score,
)
from dart_crawler.company_search import (
    _rank_entry,
    _SearchMatch,
    _SimilarityBounds,
    _top_ranked,
)
from dart_crawler.domain import MatchConfidence
from tests.company_directory_fixtures import synthetic_entries, synthetic_queries

_ENTRIES: Final = synthetic_entries(5_000, seed=20260928)
_QUERIES: Final = synthetic_queries(_ENTRIES, per_kind=36, seed=928)
_FIXED_TIERS: Final = frozenset(MatchConfidence) - {MatchConfidence.SIMILAR}


def _reference_top(query: str) -> list[_SearchMatch]:
    """What search() ranked before the directory cache: a full stable sort."""
    readings = _query_readings(query)
    return sorted(
        (_rank_entry(entry, readings) for entry in _ENTRIES),
        key=lambda match: (-match.score, match.entry.company_name),
    )[:20]


def test_top_ranked_equals_the_reference_sort_including_tie_order() -> None:
    # Given
    index = build_company_directory_index(_ENTRIES)
    queries = [query for query in _QUERIES if _query_readings(query).normalized]
    first_tiers: set[MatchConfidence] = set()
    shapes: set[str] = set()
    name_ties = 0

    for query in queries:
        # When
        expected = _reference_top(query)
        actual = _top_ranked(index, _query_readings(query))

        # Then: same entries (by identity), scores, confidences and order
        assert [(id(m.entry), m.score, m.confidence) for m in actual] == [
            (id(m.entry), m.score, m.confidence) for m in expected
        ], query
        first_tiers.add(expected[0].confidence)
        fixed = sum(match.confidence in _FIXED_TIERS for match in expected)
        shapes.add("none" if fixed == 0 else "all" if fixed == 20 else "some")
        name_ties += sum(
            (left.score, left.entry.company_name)
            == (right.score, right.entry.company_name)
            for left, right in pairwise(expected)
        )

    # The queries reach every tier, including ones where no fixed tier
    # matches, and ties that only the archive order can break.
    assert len(queries) >= 300
    assert len(_ENTRIES) >= 5_000
    assert first_tiers == set(MatchConfidence)
    assert shapes == {"none", "some", "all"}
    assert name_ties > 0


def test_readings_ranking_agrees_with_rank_company_entry_by_entry() -> None:
    index = build_company_directory_index(_ENTRIES)
    for query in _QUERIES[::6]:
        readings = _query_readings(query)
        if not readings.normalized:
            continue
        for entry, name_readings in zip(
            _ENTRIES[:1_000], index.readings[:1_000], strict=True
        ):
            expected = _rank_company(entry, readings)
            fixed = _rank_readings(entry, name_readings, readings)
            actual = (
                (_similar_score(readings, name_readings), MatchConfidence.SIMILAR)
                if fixed is None
                else (fixed.score, fixed.confidence)
            )
            assert actual == (expected.score, expected.confidence), (query, entry)


def test_similarity_bounds_repeat_difflib_and_never_undercut_the_score() -> None:
    index = build_company_directory_index(_ENTRIES)
    for query in _QUERIES[::10]:
        brand = _query_readings(query).brand
        bounds = _SimilarityBounds(brand)
        for name_readings in index.readings[:400]:
            name = name_readings.canonical
            matcher = SequenceMatcher(None, brand, name)
            score = matcher.ratio() * 100.0
            assert bounds.real_quick(name) == matcher.real_quick_ratio() * 100.0
            assert bounds.quick(name) == matcher.quick_ratio() * 100.0
            assert bounds.real_quick(name) >= bounds.quick(name) >= score


def test_empty_directory_ranks_nothing() -> None:
    index = build_company_directory_index(())

    assert _top_ranked(index, _query_readings("삼성")) == ()
