"""DS002 regular-report key-information topics (audit info first).

Every topic is one registry entry that names an OpenDART endpoint and a
Korean label; adding a topic never touches the service logic below, so
extending coverage from the initial three audit topics to the rest of DS002
is a registry-only change (see ``REPORT_TOPICS``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.domains.query_guards import (
    MAX_TOPICS_PER_QUERY,
    GuardViolation,
    guard_bsns_year,
    guard_corp_code,
    guard_reprt_code,
    guard_row_count,
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
from dart_crawler.section_models import MAX_RESPONSE_TEXT_CHARS

_SPLIT_TOPICS_NEXT_ACTION: Final = "topic을 나누어 호출하세요."


@dataclass(frozen=True, slots=True)
class ReportTopic:
    """One DS002 key-information topic: an endpoint behind a stable name."""

    key: str
    endpoint: str
    label: str


def _as_registry(*topics: ReportTopic) -> Mapping[str, ReportTopic]:
    """Build an immutable, key- and endpoint-unique registry."""
    registry: dict[str, ReportTopic] = {}
    endpoints: dict[str, str] = {}
    for topic in topics:
        if topic.key in registry:
            msg = f"duplicate report topic key: {topic.key!r}"
            raise ValueError(msg)
        if topic.endpoint in endpoints:
            msg = f"duplicate report topic endpoint: {topic.endpoint!r}"
            raise ValueError(msg)
        registry[topic.key] = topic
        endpoints[topic.endpoint] = topic.key
    return MappingProxyType(registry)


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
    """One topic's rows, returned verbatim from the source endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str
    label: str
    row_count: int
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
        registry: Mapping[str, ReportTopic] = REPORT_TOPICS,
    ) -> None:
        self._source = source
        self._registry = registry

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
            collected.append(
                ReportTopicRows(
                    topic=topic.key,
                    label=topic.label,
                    row_count=len(rows),
                    rows=rows,
                )
            )
            if not rows:
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
            next_action=_SPLIT_TOPICS_NEXT_ACTION,
        )
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        text_char_count = _total_text_char_count(collected)
        if text_char_count > MAX_RESPONSE_TEXT_CHARS:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "응답 텍스트 분량이 한 번에 반환할 수 있는 한도를 초과했습니다.",
                    retryable=False,
                    details={
                        "returned_text_char_count": text_char_count,
                        "text_char_limit": MAX_RESPONSE_TEXT_CHARS,
                    },
                ),
                next_action=_SPLIT_TOPICS_NEXT_ACTION,
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
