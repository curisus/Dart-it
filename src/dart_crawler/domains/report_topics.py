"""DS002 regular-report key-information topics (audit info first).

Every topic is one registry entry that names an OpenDART endpoint and a
Korean label; adding a topic never touches the service logic below, so
extending coverage from the initial three audit topics to the rest of DS002
is a registry-only change (see ``REPORT_TOPICS``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.domains.query_guards import (
    GuardViolation,
    guard_bsns_year,
    guard_corp_code,
    guard_reprt_code,
    guard_row_count,
    guard_text_char_count,
)
from dart_crawler.domains.registry import RegistryEntry, as_registry
from dart_crawler.query_limits import (
    DEFAULT_QUERY_LIMITS,
    MAX_TOPICS_PER_QUERY,
    QueryLimits,
)
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    JsonValue,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)

_SPLIT_TOPICS_NEXT_ACTION: Final = "topic을 나누어 호출하세요."
# Fields OpenDART echoes on every row, "해당 없음" rows included, so a row made
# only of these says nothing about the topic that was asked for.
_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "corp_code",
        "corp_cls",
        "corp_name",
        "stock_code",
        "rcept_no",
        "stlm_dt",
        "bsns_year",
        "reprt_code",
    }
)
_PLACEHOLDER: Final = "-"
# DS002 returns audit fees and hours as bare numbers: 감사보수 8,100 is 81억원,
# not 8,100원. OpenDART publishes the unit in its field documentation rather
# than in the payload, and the endpoint answers JSON with no table header to
# read it from, so the documented unit is carried alongside the rows. The
# filing itself remains authoritative if a filer states a different unit.
_TOPIC_FIELD_UNITS: Final[Mapping[str, Mapping[str, str]]] = {
    "audit_service_contract": {
        "adt_cntrct_dtls_mendng": "백만원",
        "adt_cntrct_dtls_time": "시간",
    },
}

# One DS002 key-information topic: an endpoint behind a stable name. Kept as
# an alias (rather than its own dataclass) now that domains/registry.py owns
# the shared key/endpoint/label shape used by report_topics, ownership, and
# material_events.
ReportTopic = RegistryEntry


def _as_registry(*topics: ReportTopic) -> Mapping[str, ReportTopic]:
    """Build an immutable, key- and endpoint-unique registry."""
    return as_registry(*topics, noun="report topic")


REPORT_TOPICS: Final = _as_registry(
    ReportTopic(
        "audit_opinion",
        "accnutAdtorNmNdAdtOpinion",
        "회계감사인의 명칭 및 감사의견",
    ),
    ReportTopic(
        "audit_service_contract",
        "adtServcCnclsSttus",
        "감사용역 체결현황",
    ),
    ReportTopic(
        "non_audit_service_contract",
        "accnutAdtorNonAdtServcCnclsSttus",
        "회계감사인과의 비감사용역 계약체결 현황",
    ),
    ReportTopic("dividend", "alotMatter", "배당에 관한 사항"),
    ReportTopic("capital_change", "irdsSttus", "증자(감자) 현황"),
    ReportTopic(
        "treasury_stock",
        "tesstkAcqsDspsSttus",
        "자기주식 취득 및 처분 현황",
    ),
    ReportTopic("largest_shareholder", "hyslrSttus", "최대주주 현황"),
    ReportTopic(
        "largest_shareholder_change",
        "hyslrChgSttus",
        "최대주주 변동현황",
    ),
    ReportTopic("minority_shareholders", "mrhlSttus", "소액주주 현황"),
    ReportTopic("executives", "exctvSttus", "임원 현황"),
    ReportTopic("employees", "empSttus", "직원 현황"),
    ReportTopic(
        "director_individual_pay",
        "hmvAuditIndvdlBySttus",
        "이사·감사의 개인별 보수현황(5억원 이상)",
    ),
    ReportTopic(
        "director_total_pay",
        "hmvAuditAllSttus",
        "이사·감사 전체의 보수현황(보수지급금액 - 이사·감사 전체)",
    ),
    ReportTopic(
        "individual_pay_top5",
        "indvdlByPay",
        "개인별 보수지급 금액(5억이상 상위5인)",
    ),
    ReportTopic(
        "other_corp_investment",
        "otrCprInvstmntSttus",
        "타법인 출자현황",
    ),
    ReportTopic("total_shares", "stockTotqySttus", "주식의 총수 현황"),
    ReportTopic(
        "debt_securities_issued",
        "detScritsIsuAcmslt",
        "채무증권 발행실적",
    ),
    ReportTopic(
        "commercial_paper_balance",
        "entrprsBilScritsNrdmpBlce",
        "기업어음증권 미상환 잔액",
    ),
    ReportTopic(
        "short_term_bond_balance",
        "srtpdPsndbtNrdmpBlce",
        "단기사채 미상환 잔액",
    ),
    ReportTopic(
        "corporate_bond_balance",
        "cprndNrdmpBlce",
        "회사채 미상환 잔액",
    ),
    ReportTopic(
        "hybrid_securities_balance",
        "newCaplScritsNrdmpBlce",
        "신종자본증권 미상환 잔액",
    ),
    ReportTopic(
        "contingent_capital_balance",
        "cndlCaplScritsNrdmpBlce",
        "조건부 자본증권 미상환 잔액",
    ),
    ReportTopic(
        "outside_directors",
        "outcmpnyDrctrNdChangeSttus",
        "독립(사외)이사 및 그 변동현황",
    ),
    ReportTopic(
        "unregistered_executive_pay",
        "unrstExctvMendngSttus",
        "미등기임원 보수현황",
    ),
    ReportTopic(
        "director_pay_approved",
        "drctrAdtAllMendngSttusGmtsckConfmAmount",
        "이사·감사 전체의 보수현황(주주총회 승인금액)",
    ),
    ReportTopic(
        "director_pay_by_type",
        "drctrAdtAllMendngSttusMendngPymntamtTyCl",
        "이사·감사 전체의 보수현황(보수지급금액 - 유형별)",
    ),
    ReportTopic(
        "private_fund_usage",
        "prvsrpCptalUseDtls",
        "사모자금의 사용내역",
    ),
    ReportTopic(
        "public_fund_usage",
        "pssrpCptalUseDtls",
        "공모자금의 사용내역",
    ),
)


class ReportTopicSource(Protocol):
    """OpenDART capability required by the report-topics domain service."""

    def fetch_report_topic_rows(
        self,
        endpoint: str,
        corp_code: str,
        business_year: int,
        report_code: str,
    ) -> Result[tuple[JsonObject, ...]]:
        raise NotImplementedError


class ReportTopicRows(BaseModel):
    """One topic's rows, returned verbatim from the source endpoint.

    ``row_count`` counts what OpenDART sent. ``substantive_row_count`` counts
    the rows that actually say something: "해당 없음" arrives as one row whose
    every field outside the identifiers is "-", and counting that as data hid
    the empty-topic answers this service is supposed to give.

    ``field_units`` names the unit of any field OpenDART returns as a bare
    number whose scale is documented rather than sent, so 감사보수 8,100 is not
    read as 8,100원.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str
    label: str
    row_count: int
    substantive_row_count: int
    field_units: Mapping[str, str] = {}
    rows: tuple[JsonObject, ...]


class ReportTopicData(BaseModel):
    """DS002 key-information rows for one or more topics, in request order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str
    bsns_year: int
    reprt_code: str
    returned_row_count: int
    topics: tuple[ReportTopicRows, ...]


class ReportTopicService:
    """Validate, fetch in request order, and size-guard DS002 topic requests."""

    def __init__(
        self,
        source: ReportTopicSource,
        *,
        limits: QueryLimits = DEFAULT_QUERY_LIMITS,
        registry: Mapping[str, ReportTopic] = REPORT_TOPICS,
    ) -> None:
        self._source: ReportTopicSource = source
        self._limits: QueryLimits = limits
        self._registry: Mapping[str, ReportTopic] = registry

    def get(
        self,
        corp_code: str,
        bsns_year: int,
        reprt_code: str,
        topics: tuple[str, ...],
    ) -> Result[ReportTopicData]:
        """Return the requested topics' rows, preserving request order."""
        violation = (
            guard_corp_code(corp_code)
            or guard_reprt_code(reprt_code)
            or guard_bsns_year(bsns_year)
            or self._guard_topics(topics)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        collected: list[ReportTopicRows] = []
        empty_topics: list[str] = []
        for topic_key in topics:
            topic = self._registry[topic_key]
            fetched = self._source.fetch_report_topic_rows(
                topic.endpoint,
                corp_code,
                bsns_year,
                reprt_code,
            )
            if not fetched.ok or fetched.data is None:
                if (
                    fetched.error is not None
                    and fetched.error.code is ErrorCode.NOT_FOUND
                ):
                    rows: tuple[JsonObject, ...] = ()
                else:
                    return Result.failure(
                        fetched.error
                        if fetched.error is not None
                        else error_info(
                            ErrorCode.UPSTREAM_UNAVAILABLE,
                            "OpenDART 정기보고서 주요정보를 수집할 수 없습니다.",
                            retryable=True,
                        ),
                        warnings=fetched.warnings,
                        next_action=fetched.next_action,
                    )
            else:
                # DART answers "no data" both as status 013 (a NOT_FOUND
                # failure) and as status 000 with an empty list; both must
                # count as an empty topic or the all-empty NOT_FOUND and
                # partial-collection warnings are silently bypassed.
                rows = fetched.data
            substantive_row_count = sum(1 for row in rows if _is_substantive(row))
            collected.append(
                ReportTopicRows(
                    topic=topic.key,
                    label=topic.label,
                    row_count=len(rows),
                    substantive_row_count=substantive_row_count,
                    field_units=_TOPIC_FIELD_UNITS.get(topic.key, {}),
                    rows=rows,
                )
            )
            if substantive_row_count == 0:
                empty_topics.append(topic.key)

        if empty_topics and len(empty_topics) == len(topics):
            return Result.failure(
                error_info(
                    ErrorCode.NOT_FOUND,
                    "요청한 모든 topic에서 정기보고서 주요정보를 찾지 못했습니다.",
                    retryable=False,
                    details={"empty_topics": list(empty_topics)},
                ),
                next_action="다른 bsns_year 또는 reprt_code로 다시 시도하세요.",
            )

        total_row_count = sum(item.row_count for item in collected)
        row_violation = guard_row_count(
            total_row_count,
            limits=self._limits,
            next_action=_SPLIT_TOPICS_NEXT_ACTION,
        )
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        text_char_count = _total_text_char_count(collected)
        text_violation = guard_text_char_count(
            text_char_count,
            limits=self._limits,
            next_action=_SPLIT_TOPICS_NEXT_ACTION,
        )
        if text_violation is not None:
            return Result.failure(
                text_violation.error,
                next_action=text_violation.next_action,
            )

        warnings: tuple[WarningInfo, ...] = ()
        if empty_topics:
            warnings = (
                WarningInfo(
                    code=WarningCode.PARTIAL_COLLECTION,
                    message="일부 topic에서 정기보고서 주요정보를 찾지 못했습니다.",
                    details={"empty_topics": list(empty_topics)},
                ),
            )

        return Result.success(
            ReportTopicData(
                corp_code=corp_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                returned_row_count=total_row_count,
                topics=tuple(collected),
            ),
            warnings=warnings,
        )

    def _guard_topics(self, topics: tuple[str, ...]) -> GuardViolation | None:
        if not topics:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "topics가 비어 있습니다.",
                    retryable=False,
                ),
                next_action=_supported_topics_next_action(self._registry),
            )
        if len(topics) > MAX_TOPICS_PER_QUERY:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "topics 개수가 한 번에 조회할 수 있는 한도를 초과했습니다.",
                    retryable=False,
                    details={
                        "topic_count": len(topics),
                        "limit": MAX_TOPICS_PER_QUERY,
                    },
                ),
                next_action="topic을 나누어 호출하세요.",
            )
        duplicates = _duplicates(topics)
        if duplicates:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "topics에 중복된 값이 있습니다.",
                    retryable=False,
                    details={"duplicate_topics": list(duplicates)},
                ),
                next_action="topic 값을 중복 없이 지정하세요.",
            )
        unknown = tuple(topic for topic in topics if topic not in self._registry)
        if unknown:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "지원하지 않는 topic 값입니다.",
                    retryable=False,
                    details={
                        "unknown_topics": list(unknown),
                        "supported_topics": _supported_topics(self._registry),
                    },
                ),
                next_action=_supported_topics_next_action(self._registry),
            )
        return None


def _supported_topics(registry: Mapping[str, ReportTopic]) -> list[JsonValue]:
    return [{"topic": topic.key, "label": topic.label} for topic in registry.values()]


def _supported_topics_next_action(registry: Mapping[str, ReportTopic]) -> str:
    return f"{', '.join(registry)} 중 하나 이상을 topics에 지정하세요."


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _is_substantive(row: JsonObject) -> bool:
    """Whether a row says anything beyond identifying the company and filing."""
    return any(
        _carries_content(value)
        for name, value in row.items()
        if name not in _IDENTITY_FIELDS
    )


def _carries_content(value: JsonValue) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        return bool(stripped) and stripped != _PLACEHOLDER
    return True


def _total_text_char_count(topics: list[ReportTopicRows]) -> int:
    return sum(_json_text_char_count(row) for topic in topics for row in topic.rows)


def _json_text_char_count(value: JsonValue) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_json_text_char_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_json_text_char_count(item) for item in value)
    return 0
