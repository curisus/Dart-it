"""Ranked company search over the cached OpenDART company directory."""

from __future__ import annotations

from bisect import insort
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from heapq import heapify, heappop
from typing import Final, Protocol, assert_never

from dart_crawler.api_models import DartListRow
from dart_crawler.company_directory import (
    CompanyDirectoryIndex,
    CompanyDirectorySource,
    load_company_directory,
)

# Re-exported: the latency probes time the directory parse under this name.
from dart_crawler.company_directory import (
    _parse_company_archive as _parse_company_archive,  # noqa: PLC0414
)
from dart_crawler.company_name_matching import (
    CompanyCode,
    _query_readings,
    _QueryReadings,
    _rank_company,
    _rank_readings,
    _similar_score,
)
from dart_crawler.domain import Company, Market, MatchConfidence, ReportKind
from dart_crawler.filing_service import (
    matches_report_kind,
    validate_report_kind,
)
from dart_crawler.result import ErrorCode, ErrorInfo, Result, error_info


class CompanySource(CompanyDirectorySource, Protocol):
    """OpenDART capabilities required by company search."""

    def list_disclosures(
        self,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _SearchMatch:
    """Internal ranking data for one company search candidate."""

    entry: CompanyCode
    score: float
    confidence: MatchConfidence


@dataclass(frozen=True, slots=True)
class _FilteredCandidates:
    """Candidates that have the report kind, or the upstream failure to return."""

    companies: tuple[Company, ...]
    selected: tuple[_SearchMatch, ...]
    upstream_failure: Result[tuple[DartListRow, ...]] | None = None


_WEAK_MATCH_SCORE: Final[float] = 85.0
_WEAK_MATCH_NEXT_ACTION: Final[str] = (
    "정확히 일치하는 회사명이 없습니다. 아래 번호 목록에서 회사를 선택하세요."
)
_ARCHIVE_NOT_FOUND_MESSAGE: Final[str] = (
    "회사코드 목록에서 일치하는 회사를 찾지 못했습니다."
)
_ARCHIVE_NOT_FOUND_NEXT_ACTION: Final[str] = (
    "회사명, 종목코드 또는 회사코드 일부를 확인하세요."
)
_UPSTREAM_FAILURE_NEXT_ACTION: Final[str] = (
    "OpenDART API 키와 네트워크 상태를 확인한 뒤 다시 시도하세요."
)
# Only this many best-ranked candidates are ever used: the first five as the
# answer, or up to twenty checked for the requested report kind.
_RANKED_CANDIDATES: Final[int] = 20
_RESULT_LIMIT: Final[int] = 5


class CompanySearchService:
    """Search the OpenDART company directory; only the directory is cached."""

    def __init__(self, source: CompanySource) -> None:
        self._source = source

    def search(
        self,
        query: str,
        report_kind: ReportKind | str | None,
    ) -> Result[tuple[Company, ...]]:
        """Return up to five ranked companies, optionally filtered by filings."""
        violation = (
            None if report_kind is None else validate_report_kind(report_kind)
        )
        if violation is not None:
            return Result.failure(
                violation.error,
                next_action=violation.next_action,
            )
        parsed_kind = None if report_kind is None else ReportKind(report_kind)
        query_readings = _query_readings(query)
        if not query_readings.normalized:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "회사 검색어가 비어 있습니다.",
                    retryable=False,
                ),
                next_action="회사명 또는 종목코드를 입력하세요.",
            )
        directory = load_company_directory(self._source)
        if not directory.ok or directory.data is None:
            return Result.failure(
                directory.error
                if directory.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "회사코드 목록을 수집할 수 없습니다.",
                    retryable=True,
                ),
                next_action=directory.next_action,
            )
        ranked = _top_ranked(directory.data, query_readings)
        matches: list[Company]
        selected_matches: list[_SearchMatch]
        if parsed_kind is None:
            selected_matches = list(ranked[:_RESULT_LIMIT])
            matches = [
                Company(
                    company_name=match.entry.company_name,
                    corp_code=match.entry.corp_code,
                    stock_code=match.entry.stock_code,
                    market=None,
                    ranking=ranking,
                    match_confidence=match.confidence,
                )
                for ranking, match in enumerate(selected_matches, start=1)
            ]
        else:
            filtered = self._filter_disclosures(ranked, parsed_kind)
            if filtered.upstream_failure is not None:
                return _upstream_failure(filtered.upstream_failure)
            matches = list(filtered.companies)
            selected_matches = list(filtered.selected)
        if not matches:
            return _not_found(parsed_kind is None)
        return Result.success(
            tuple(matches),
            next_action=_weak_match_next_action(selected_matches[0]),
        )


    def _filter_disclosures(
        self,
        ranked: Sequence[_SearchMatch],
        report_kind: ReportKind,
    ) -> _FilteredCandidates:
        detail_type = _detail_type(report_kind)
        matches: list[Company] = []
        selected_matches: list[_SearchMatch] = []
        failures: list[Result[tuple[DartListRow, ...]]] = []
        attempts = 0
        for match in ranked[:_RANKED_CANDIDATES]:
            rows_result = self._source.list_disclosures(
                match.entry.corp_code,
                detail_type,
            )
            attempts += 1
            if not rows_result.ok:
                # With a shared directory a bad key first fails here; it must
                # not be reported as "no company has the report".
                if _error_code(rows_result.error) is ErrorCode.UPSTREAM_AUTH:
                    return _FilteredCandidates((), (), rows_result)
                failures.append(rows_result)
                continue
            if not rows_result.data or not any(
                matches_report_kind(report_kind, row.report_nm)
                for row in rows_result.data
            ):
                continue
            selected_matches.append(match)
            matches.append(
                Company(
                    company_name=match.entry.company_name,
                    corp_code=match.entry.corp_code,
                    stock_code=match.entry.stock_code,
                    market=_market(rows_result.data),
                    ranking=len(matches) + 1,
                    match_confidence=match.confidence,
                )
            )
            if len(matches) == _RESULT_LIMIT:
                break
        every_attempt_failed = bool(failures) and len(failures) == attempts
        if every_attempt_failed and not any(
            _error_code(failure.error) is ErrorCode.NOT_FOUND for failure in failures
        ):
            return _FilteredCandidates((), (), failures[0])
        return _FilteredCandidates(tuple(matches), tuple(selected_matches))


def _error_code(error: ErrorInfo | None) -> ErrorCode | None:
    return None if error is None else error.code


def _upstream_failure(
    failure: Result[tuple[DartListRow, ...]],
) -> Result[tuple[Company, ...]]:
    return Result.failure(
        failure.error
        if failure.error is not None
        else error_info(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "OpenDART 공시 검색에 실패했습니다.",
            retryable=True,
        ),
        warnings=failure.warnings,
        next_action=(
            failure.next_action
            if failure.next_action is not None
            else _UPSTREAM_FAILURE_NEXT_ACTION
        ),
    )


def _not_found(archive_only: bool) -> Result[tuple[Company, ...]]:
    return Result.failure(
        error_info(
            ErrorCode.NOT_FOUND,
            _ARCHIVE_NOT_FOUND_MESSAGE
            if archive_only
            else "대상 보고서가 존재하는 회사를 찾지 못했습니다.",
            retryable=False,
        ),
        next_action=(
            _ARCHIVE_NOT_FOUND_NEXT_ACTION
            if archive_only
            else "회사명, 종목코드, 보고서 종류를 확인하세요."
        ),
    )


def _rank_entry(
    entry: CompanyCode,
    query: _QueryReadings,
) -> _SearchMatch:
    """Reference ranking of one entry; _top_ranked must agree with it."""
    match = _rank_company(entry, query)
    return _SearchMatch(entry, match.score, match.confidence)


# (-score, company_name, archive index, confidence): the index is unique, so
# comparison never reaches the confidence.
type _RankKey = tuple[float, str, int, MatchConfidence]


class _BestKeys:
    """The smallest rank keys offered so far, at most `limit`, kept sorted."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self.keys: list[_RankKey] = []

    def floor_score(self) -> float | None:
        """The worst kept score once full: a candidate below it cannot enter."""
        if len(self.keys) < self._limit:
            return None
        return -self.keys[-1][0]

    def offer(self, key: _RankKey) -> None:
        if len(self.keys) < self._limit:
            insort(self.keys, key)
        elif key < self.keys[-1]:
            insort(self.keys, key)
            self.keys.pop()


class _SimilarityBounds:
    """Upper bounds of SequenceMatcher(None, query, name).ratio() * 100.

    They repeat difflib's real_quick_ratio and quick_ratio arithmetic exactly
    (the same integer counts through the same 2.0 * matches / length), so each
    bound is never below the score it stands for.
    """

    def __init__(self, query: str) -> None:
        self._length = len(query)
        self._counts = tuple(Counter(query).items())

    def real_quick(self, name: str) -> float:
        return _percent(min(self._length, len(name)), self._length + len(name))

    def quick(self, name: str) -> float:
        # quick_ratio counts the characters the two strings share as
        # multisets: the sum over the query's characters of the smaller count.
        matches = 0
        for char, query_count in self._counts:
            name_count = name.count(char)
            matches += min(query_count, name_count)
        return _percent(matches, self._length + len(name))


def _percent(matches: int, length: int) -> float:
    # difflib._calculate_ratio, then the * 100.0 of _similar_score.
    return (2.0 * matches / length if length else 1.0) * 100.0


def _top_ranked(
    directory: CompanyDirectoryIndex,
    query: _QueryReadings,
) -> tuple[_SearchMatch, ...]:
    """Exactly sorted(ranked, key=(-score, company_name))[:20] of every entry.

    The reference sort is stable, so (score, name) ties keep archive order;
    the archive index in the key reproduces that. Fixed-score tiers are ranked
    first so the 20th-best score is known early. A SIMILAR candidate whose
    upper bound is strictly below the 20th-best score (once there are 20) can
    never enter, so its SequenceMatcher.ratio is skipped; an equal bound is
    still scored because the name may win the tie.
    """
    best = _BestKeys(_RANKED_CANDIDATES)
    entries = directory.entries
    readings = directory.readings
    similar: list[int] = []
    for index, entry in enumerate(entries):
        match = _rank_readings(entry, readings[index], query)
        if match is None:
            similar.append(index)
        else:
            best.offer((-match.score, entry.company_name, index, match.confidence))
    bounds = _SimilarityBounds(query.brand)
    floor = best.floor_score()
    candidates: list[tuple[float, int]] = []
    for index in similar:
        canonical = readings[index].canonical
        if floor is not None and bounds.real_quick(canonical) < floor:
            continue
        bound = bounds.quick(canonical)
        if floor is not None and bound < floor:
            continue
        candidates.append((-bound, index))
    # Highest bound first raises the 20th-best score as early as possible;
    # once a bound is strictly below it, every remaining bound is too.
    heapify(candidates)
    while candidates:
        negative_bound, index = heappop(candidates)
        floor = best.floor_score()
        if floor is not None and -negative_bound < floor:
            break
        best.offer(
            (
                -_similar_score(query, readings[index]),
                entries[index].company_name,
                index,
                MatchConfidence.SIMILAR,
            )
        )
    return tuple(
        _SearchMatch(entries[index], -negative_score, confidence)
        for negative_score, _, index, confidence in best.keys
    )


def _weak_match_next_action(match: _SearchMatch) -> str | None:
    if (
        match.confidence is MatchConfidence.SIMILAR
        and match.score < _WEAK_MATCH_SCORE
    ):
        return _WEAK_MATCH_NEXT_ACTION
    return None


def _detail_type(report_kind: ReportKind) -> str:
    match report_kind:
        case ReportKind.AUDIT:
            return "A001"
        case ReportKind.HALF_YEAR_REVIEW:
            return "A002"
        case ReportKind.QUARTERLY_REVIEW:
            return "A003"
        case unreachable:
            assert_never(unreachable)


def _market(rows: Sequence[DartListRow]) -> Market:
    for row in rows:
        try:
            return Market(row.corp_cls)
        except ValueError:
            continue
    return Market.OTHER
