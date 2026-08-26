"""DS005 주요사항보고(material events) 36-endpoint registry and query service.

Every event type is one registry entry that names an OpenDART endpoint and a
Korean label, mirroring the registry pattern of report_topics.py (DS002) and
ownership.py (DS004) — all three now build on domains/registry.py's shared
RegistryEntry/as_registry. Extending coverage is a registry-only change (see
``MATERIAL_EVENTS``).

Two things set this domain apart from its siblings:

- bgn_de/end_de are REQUIRED (unlike ownership.py, where both are optional
  and narrow an unbounded history fetched once): OpenDART's DS005 endpoints
  themselves demand a receipt-date range, so a missing bound is rejected
  before any network call rather than defaulted or filtered client-side.
- an all-empty result still SUCCEEDS with a warning (see MaterialEventService
  .get's docstring for why that differs from report_topics.get's all-empty
  NOT_FOUND).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.domains.query_guards import (
    GuardViolation,
    guard_corp_code,
    guard_required_date_range,
    guard_row_count,
    guard_text_char_count,
)
from dart_crawler.domains.registry import RegistryEntry, as_registry
from dart_crawler.query_limits import DEFAULT_QUERY_LIMITS, QueryLimits
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    JsonValue,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)

_SPLIT_NEXT_ACTION: Final = "기간을 좁히거나 event_type을 나누어 호출하세요."
_SUPPORTED_EVENT_TYPES_NEXT_ACTION: Final = (
    "지원 event_type 목록은 오류 details의 supported_event_types를 확인하세요."
)

MATERIAL_EVENTS: Final = as_registry(
    RegistryEntry("bankruptcy", "dfOcr", "부도발생"),
    RegistryEntry("business_suspension", "bsnSp", "영업정지"),
    RegistryEntry("rehabilitation_filing", "ctrcvsBgrq", "회생절차 개시신청"),
    RegistryEntry("dissolution", "dsRsOcr", "해산사유 발생"),
    RegistryEntry("paid_in_capital_increase", "piicDecsn", "유상증자 결정"),
    RegistryEntry("free_capital_increase", "fricDecsn", "무상증자 결정"),
    RegistryEntry("paid_in_and_free_increase", "pifricDecsn", "유무상증자 결정"),
    RegistryEntry("capital_reduction", "crDecsn", "감자 결정"),
    RegistryEntry(
        "creditor_management_start", "bnkMngtPcbg", "채권은행 등의 관리절차 개시"
    ),
    RegistryEntry("lawsuit", "lwstLg", "소송 등의 제기"),
    RegistryEntry(
        "overseas_listing_decision", "ovLstDecsn", "해외 증권시장 주권등 상장 결정"
    ),
    RegistryEntry(
        "overseas_delisting_decision",
        "ovDlstDecsn",
        "해외 증권시장 주권등 상장폐지 결정",
    ),
    RegistryEntry("overseas_listing", "ovLst", "해외 증권시장 주권등 상장"),
    RegistryEntry("overseas_delisting", "ovDlst", "해외 증권시장 주권등 상장폐지"),
    RegistryEntry("convertible_bond_issue", "cvbdIsDecsn", "전환사채권 발행결정"),
    RegistryEntry(
        "bond_with_warrant_issue", "bdwtIsDecsn", "신주인수권부사채권 발행결정"
    ),
    RegistryEntry("exchangeable_bond_issue", "exbdIsDecsn", "교환사채권 발행결정"),
    RegistryEntry(
        "creditor_management_stop", "bnkMngtPcsp", "채권은행 등의 관리절차 중단"
    ),
    RegistryEntry(
        "writedown_contingent_bond_issue",
        "wdCocobdIsDecsn",
        "상각형 조건부자본증권 발행결정",
    ),
    RegistryEntry(
        "asset_transfer_putback_option",
        "astInhtrfEtcPtbkOpt",
        "자산양수도(기타), 풋백옵션",
    ),
    RegistryEntry(
        "other_corp_stock_transfer",
        "otcprStkInvscrTrfDecsn",
        "타법인 주식 및 출자증권 양도결정",
    ),
    RegistryEntry("tangible_asset_transfer", "tgastTrfDecsn", "유형자산 양도 결정"),
    RegistryEntry("tangible_asset_acquisition", "tgastInhDecsn", "유형자산 양수 결정"),
    RegistryEntry(
        "other_corp_stock_acquisition",
        "otcprStkInvscrInhDecsn",
        "타법인 주식 및 출자증권 양수결정",
    ),
    RegistryEntry("business_transfer", "bsnTrfDecsn", "영업양도 결정"),
    RegistryEntry("business_acquisition", "bsnInhDecsn", "영업양수 결정"),
    RegistryEntry(
        "treasury_trust_cancel",
        "tsstkAqTrctrCcDecsn",
        "자기주식취득 신탁계약 해지 결정",
    ),
    RegistryEntry(
        "treasury_trust_contract",
        "tsstkAqTrctrCnsDecsn",
        "자기주식취득 신탁계약 체결 결정",
    ),
    RegistryEntry("treasury_stock_disposal", "tsstkDpDecsn", "자기주식 처분 결정"),
    RegistryEntry("treasury_stock_acquisition", "tsstkAqDecsn", "자기주식 취득 결정"),
    RegistryEntry("merger", "cmpMgDecsn", "회사합병 결정"),
    RegistryEntry("split_merger", "cmpDvmgDecsn", "회사분할합병 결정"),
    RegistryEntry("company_split", "cmpDvDecsn", "회사분할 결정"),
    RegistryEntry("stock_exchange_transfer", "stkExtrDecsn", "주식교환·이전 결정"),
    RegistryEntry(
        "stock_related_bond_acquisition",
        "stkrtbdInhDecsn",
        "주권 관련 사채권 양수 결정",
    ),
    RegistryEntry(
        "stock_related_bond_transfer", "stkrtbdTrfDecsn", "주권 관련 사채권 양도 결정"
    ),
    noun="material event",
)


class MaterialEventSource(Protocol):
    """OpenDART capability required by the material-events domain service."""

    def fetch_material_event_rows(
        self,
        endpoint: str,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[tuple[JsonObject, ...]]:
        raise NotImplementedError


class MaterialEventRows(BaseModel):
    """One event type's rows, returned verbatim from the source endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str
    label: str
    row_count: int
    rows: tuple[JsonObject, ...]


class MaterialEventData(BaseModel):
    """DS005 주요사항보고 rows for one or more event types, in request order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str
    bgn_de: str
    end_de: str
    returned_row_count: int
    events: tuple[MaterialEventRows, ...]


class MaterialEventService:
    """Validate, fetch in request order, and size-guard DS005 event requests."""

    def __init__(
        self,
        source: MaterialEventSource,
        *,
        limits: QueryLimits = DEFAULT_QUERY_LIMITS,
        registry: Mapping[str, RegistryEntry] = MATERIAL_EVENTS,
    ) -> None:
        self._source: MaterialEventSource = source
        self._limits: QueryLimits = limits
        self._registry: Mapping[str, RegistryEntry] = registry

    def get(
        self,
        corp_code: str,
        event_types: tuple[str, ...],
        bgn_de: str,
        end_de: str,
    ) -> Result[MaterialEventData]:
        """Return the requested material-event types' rows, preserving request order.

        bgn_de/end_de are REQUIRED (unlike ownership.py's optional range):
        DART's DS005 endpoints demand a receipt-date range themselves, so a
        missing bound is rejected here before any network call.

        A company having filed no material events of the requested types in
        the given period is itself the answer, not a partial failure — so
        unlike report_topics.get (where every topic empty means the
        requested bsns_year/reprt_code filing genuinely does not exist and
        the call fails NOT_FOUND), this always succeeds: every event_type
        gets an entry (possibly with zero rows), and one PARTIAL_COLLECTION
        warning names whichever types came back empty, whether that is some
        of them or every one of them.
        """
        violation = (
            guard_corp_code(corp_code)
            or guard_required_date_range(bgn_de, end_de)
            or self._guard_event_types(event_types)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        collected: list[MaterialEventRows] = []
        empty_event_types: list[str] = []
        for event_key in event_types:
            event = self._registry[event_key]
            fetched = self._source.fetch_material_event_rows(
                event.endpoint, corp_code, bgn_de, end_de
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
                            "OpenDART 주요사항보고 정보를 수집할 수 없습니다.",
                            retryable=True,
                        ),
                        warnings=fetched.warnings,
                        next_action=fetched.next_action,
                    )
            else:
                # DART answers "no data" both as status 013 (a NOT_FOUND
                # failure) and as status 000 with an empty list; both must
                # count as an empty event type or the partial-collection
                # warning is silently bypassed for one of the two shapes.
                rows = fetched.data
            collected.append(
                MaterialEventRows(
                    event_type=event.key,
                    label=event.label,
                    row_count=len(rows),
                    rows=rows,
                )
            )
            if not rows:
                empty_event_types.append(event.key)

        total_row_count = sum(item.row_count for item in collected)
        row_violation = guard_row_count(
            total_row_count,
            limits=self._limits,
            next_action=_SPLIT_NEXT_ACTION,
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
            next_action=_SPLIT_NEXT_ACTION,
        )
        if text_violation is not None:
            return Result.failure(
                text_violation.error,
                next_action=text_violation.next_action,
            )

        warnings: tuple[WarningInfo, ...] = ()
        if empty_event_types:
            warnings = (
                WarningInfo(
                    code=WarningCode.PARTIAL_COLLECTION,
                    message="일부 event_type에서 주요사항보고 정보를 찾지 못했습니다.",
                    details={"empty_event_types": list(empty_event_types)},
                ),
            )

        return Result.success(
            MaterialEventData(
                corp_code=corp_code,
                bgn_de=bgn_de,
                end_de=end_de,
                returned_row_count=total_row_count,
                events=tuple(collected),
            ),
            warnings=warnings,
        )

    def _guard_event_types(self, event_types: tuple[str, ...]) -> GuardViolation | None:
        if not event_types:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "event_types가 비어 있습니다.",
                    retryable=False,
                ),
                next_action=_SUPPORTED_EVENT_TYPES_NEXT_ACTION,
            )
        if len(event_types) > self._limits.max_topics_per_query:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "event_types 개수가 한 번에 조회할 수 있는 한도를 초과했습니다.",
                    retryable=False,
                    details={
                        "event_type_count": len(event_types),
                        "limit": self._limits.max_topics_per_query,
                    },
                ),
                next_action="event_type을 나누어 호출하세요.",
            )
        duplicates = _duplicates(event_types)
        if duplicates:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "event_types에 중복된 값이 있습니다.",
                    retryable=False,
                    details={"duplicate_event_types": list(duplicates)},
                ),
                next_action="event_type 값을 중복 없이 지정하세요.",
            )
        unknown = tuple(
            event_type for event_type in event_types if event_type not in self._registry
        )
        if unknown:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "지원하지 않는 event_type 값입니다.",
                    retryable=False,
                    details={
                        "unknown_event_types": list(unknown),
                        "supported_event_types": _supported_event_types(self._registry),
                    },
                ),
                next_action=_SUPPORTED_EVENT_TYPES_NEXT_ACTION,
            )
        return None


def _supported_event_types(registry: Mapping[str, RegistryEntry]) -> list[JsonValue]:
    return [
        {"event_type": event.key, "label": event.label} for event in registry.values()
    ]


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


# Mirrors domains/report_topics.py's _total_text_char_count /
# _json_text_char_count (also duplicated in domains/ownership.py). Each is a
# module-private helper of its own registry service, so this is duplicated
# rather than imported.
def _total_text_char_count(events: list[MaterialEventRows]) -> int:
    return sum(_json_text_char_count(row) for event in events for row in event.rows)


def _json_text_char_count(value: JsonValue) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_json_text_char_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_json_text_char_count(item) for item in value)
    return 0
