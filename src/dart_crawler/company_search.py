"""Company-code archive parsing and ranked company search."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, assert_never

from defusedxml import ElementTree

from dart_crawler.api_models import DartListRow
from dart_crawler.company_name_matching import (
    CompanyCode,
    _query_readings,
    _QueryReadings,
    _rank_company,
)
from dart_crawler.domain import Company, Market, MatchConfidence, ReportKind
from dart_crawler.filing_service import matches_report_kind
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.zip_safety import ArchiveLimits, read_member


class CompanySource(Protocol):
    """OpenDART capabilities required by company search."""

    def download_company_codes(self) -> Result[bytes]:
        raise NotImplementedError

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


_WEAK_MATCH_SCORE: Final[float] = 85.0
_WEAK_MATCH_NEXT_ACTION: Final[str] = (
    "정확히 일치하는 회사명이 없습니다. 아래 번호 목록에서 회사를 선택하세요."
)


class CompanySearchService:
    """Search the OpenDART company directory without persistent state."""

    def __init__(self, source: CompanySource) -> None:
        self._source = source

    def search(
        self,
        query: str,
        report_kind: ReportKind | str,
    ) -> Result[tuple[Company, ...]]:
        """Return up to five companies with the requested target filing."""
        try:
            parsed_kind = ReportKind(report_kind)
        except ValueError:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "report_kind가 지원 범위에 없습니다.",
                    retryable=False,
                ),
                next_action="audit, quarterly_review, half_year_review 중 하나를 입력하세요.",
            )
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
        archive = self._source.download_company_codes()
        if not archive.ok or archive.data is None:
            return Result.failure(
                archive.error
                if archive.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "회사코드 목록을 수집할 수 없습니다.",
                    retryable=True,
                ),
                next_action="잠시 후 회사 검색을 다시 시도하세요.",
            )
        parsed_archive = _parse_company_archive(archive.data)
        if not parsed_archive.ok or parsed_archive.data is None:
            return Result.failure(
                parsed_archive.error
                if parsed_archive.error is not None
                else error_info(
                    ErrorCode.PARSE_FAILED,
                    "회사코드 목록을 해석할 수 없습니다.",
                    retryable=False,
                ),
                next_action="OpenDART 회사코드 파일 형식을 확인하세요.",
            )
        ranked = sorted(
            (
                _rank_entry(entry, query_readings)
                for entry in parsed_archive.data
            ),
            key=lambda match: (-match.score, match.entry.company_name),
        )
        matches: list[Company] = []
        selected_matches: list[_SearchMatch] = []
        detail_type = _detail_type(parsed_kind)
        for match in ranked[:20]:
            entry = match.entry
            rows_result = self._source.list_disclosures(entry.corp_code, detail_type)
            if (
                not rows_result.ok
                or not rows_result.data
                or not any(
                    matches_report_kind(parsed_kind, row.report_nm)
                    for row in rows_result.data
                )
            ):
                continue
            market = _market(rows_result.data)
            matches.append(
                Company(
                    company_name=entry.company_name,
                    corp_code=entry.corp_code,
                    stock_code=entry.stock_code,
                    market=market,
                    ranking=len(matches) + 1,
                    match_confidence=match.confidence,
                )
            )
            selected_matches.append(match)
            if len(matches) == 5:
                break
        if not matches:
            return Result.failure(
                error_info(
                    ErrorCode.NOT_FOUND,
                    "대상 보고서가 존재하는 회사를 찾지 못했습니다.",
                    retryable=False,
                ),
                next_action="회사명, 종목코드, 보고서 종류를 확인하세요.",
            )
        return Result.success(
            tuple(matches),
            next_action=_weak_match_next_action(selected_matches[0]),
        )


def _parse_company_archive(content: bytes) -> Result[tuple[CompanyCode, ...]]:
    from dart_crawler.zip_safety import inspect_archive

    inspection = inspect_archive(content, limits=ArchiveLimits())
    if not inspection.ok or inspection.data is None:
        return Result.failure(
            inspection.error
            if inspection.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED,
                "회사코드 ZIP이 잘못되었습니다.",
                retryable=False,
            )
        )
    xml_name = next(
        (
            member.name
            for member in inspection.data
            if member.name.casefold().endswith("corpcode.xml")
        ),
        None,
    )
    if xml_name is None:
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "CORPCODE.xml을 찾지 못했습니다.",
                retryable=False,
            )
        )
    xml_result = read_member(content, xml_name, limits=ArchiveLimits())
    if not xml_result.ok or xml_result.data is None:
        return Result.failure(
            xml_result.error
            if xml_result.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED,
                "CORPCODE.xml을 읽지 못했습니다.",
                retryable=False,
            )
        )
    try:
        root = ElementTree.fromstring(xml_result.data)
    except ElementTree.ParseError:
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "CORPCODE.xml 형식이 잘못되었습니다.",
                retryable=False,
            )
        )
    entries: list[CompanyCode] = []
    for item in root.findall("./list"):
        corp_code = item.findtext("corp_code", "")
        company_name = item.findtext("corp_name", "").strip()
        stock_code = item.findtext("stock_code", "").strip() or None
        if len(corp_code) != 8 or not corp_code.isdigit() or not company_name:
            continue
        entries.append(CompanyCode(corp_code, company_name, stock_code))
    return Result.success(tuple(entries))


def _rank_entry(
    entry: CompanyCode,
    query: _QueryReadings,
) -> _SearchMatch:
    match = _rank_company(entry, query)
    return _SearchMatch(entry, match.score, match.confidence)


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
