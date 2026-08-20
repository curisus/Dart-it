"""DS004 major-holding and insider-ownership disclosure lookups.

Every report type is one registry entry that names an OpenDART endpoint and a
Korean label, mirroring the registry pattern of report_topics.py. Unlike
report_topics, one call fetches exactly one report type (no batching), and a
company with no reports of that type succeeds with zero rows rather than
failing — see OwnershipService.get for why that differs from report_topics'
all-empty NOT_FOUND policy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.domains.query_guards import (
    GuardViolation,
    guard_corp_code,
    guard_row_count,
)
from dart_crawler.domains.registry import RegistryEntry, as_registry
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

_SPLIT_NEXT_ACTION: Final = (
    "bgn_de와 end_de(YYYYMMDD)로 접수일 기간을 좁혀 다시 호출하세요."
)
_DATE_PATTERN: Final = re.compile(r"^\d{8}$", re.ASCII)
_DATE_FORMAT_NEXT_ACTION: Final = "bgn_de와 end_de를 YYYYMMDD 형식으로 입력하세요."
_DATE_ORDER_NEXT_ACTION: Final = "bgn_de가 end_de보다 늦지 않도록 입력하세요."

# One DS004 ownership report type: an endpoint behind a stable name. Kept as
# an alias (rather than its own dataclass) now that domains/registry.py owns
# the shared key/endpoint/label shape used by report_topics, ownership, and
# material_events.
OwnershipReport = RegistryEntry


def _as_report_registry(*reports: OwnershipReport) -> Mapping[str, OwnershipReport]:
    """Build an immutable, key- and endpoint-unique registry."""
    return as_registry(*reports, noun="ownership report")


OWNERSHIP_REPORTS: Final = _as_report_registry(
    OwnershipReport("major_holding", "majorstock", "대량보유 상황보고"),
    OwnershipReport("insider_ownership", "elestock", "임원ㆍ주요주주 소유보고"),
)


class OwnershipSource(Protocol):
    """OpenDART capability required by the ownership domain service."""

    def fetch_ownership_rows(
        self,
        endpoint: str,
        corp_code: str,
    ) -> Result[tuple[JsonObject, ...]]:
        raise NotImplementedError


class OwnershipReportData(BaseModel):
    """One DS004 report type's rows, returned verbatim for one company.

    total_row_count is the row count OpenDART returned before the optional
    bgn_de/end_de receipt-date filter narrowed it; returned_row_count is the
    count after filtering. They differ only when a range was supplied (or
    narrower than the full result), so callers can tell a filter narrowed
    the answer apart from the source genuinely having fewer rows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str
    report_type: str
    label: str
    bgn_de: str
    end_de: str
    total_row_count: int
    returned_row_count: int
    rows: tuple[JsonObject, ...]


class OwnershipService:
    """Validate, fetch, and size-guard one DS004 ownership-report request."""

    def __init__(
        self,
        source: OwnershipSource,
        *,
        registry: Mapping[str, OwnershipReport] = OWNERSHIP_REPORTS,
    ) -> None:
        self._source = source
        self._registry = registry

    def get(
        self,
        corp_code: str,
        report_type: str,
        bgn_de: str = "",
        end_de: str = "",
    ) -> Result[OwnershipReportData]:
        """Return one ownership report type's rows for one company.

        A company legitimately may have no 대량보유 or 임원·주요주주 reports, and
        unlike report_topics (which batches many topics and only fails when
        every one of them is empty), one call here answers exactly one report
        type — so an empty result is the caller's real answer, not a partial
        failure: it succeeds with zero rows and a warning instead of a hard
        NOT_FOUND.

        bgn_de/end_de (both optional, YYYYMMDD) narrow the returned rows to
        those whose receipt date falls in [bgn_de, end_de], inclusive on both
        ends; an empty string leaves that side of the range open. DART's
        majorstock/elestock endpoints accept no date params of their own, so
        every row is fetched first and the range is applied locally — this is
        the split dimension a caller uses when a company's full report
        history is larger than the response budget (Samsung's
        insider_ownership history, for example).
        """
        violation = (
            guard_corp_code(corp_code)
            or self._guard_report_type(report_type)
            or _guard_date_range(bgn_de, end_de)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        report = self._registry[report_type]
        fetched = self._source.fetch_ownership_rows(report.endpoint, corp_code)
        if not fetched.ok or fetched.data is None:
            if fetched.error is not None and fetched.error.code is ErrorCode.NOT_FOUND:
                return Result.success(
                    OwnershipReportData(
                        corp_code=corp_code,
                        report_type=report.key,
                        label=report.label,
                        bgn_de=bgn_de,
                        end_de=end_de,
                        total_row_count=0,
                        returned_row_count=0,
                        rows=(),
                    ),
                    warnings=(_empty_warning(report.key),),
                )
            return Result.failure(
                fetched.error
                if fetched.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 지분공시 정보를 수집할 수 없습니다.",
                    retryable=True,
                ),
                warnings=fetched.warnings,
                next_action=fetched.next_action,
            )

        # DART answers "no data" both as status 013 (handled above as a
        # NOT_FOUND failure) and as status 000 with an empty list; both must
        # count as an empty report or the partial-collection warning is
        # silently bypassed for one of the two shapes. This check is on the
        # unfiltered rows: an empty result *after* filtering is the caller's
        # own choice of range, not a source that had nothing to offer.
        rows = fetched.data
        warnings: tuple[WarningInfo, ...] = ()
        if not rows:
            warnings = (_empty_warning(report.key),)

        filtered_rows = tuple(row for row in rows if _row_in_range(row, bgn_de, end_de))

        row_violation = guard_row_count(
            len(filtered_rows), next_action=_SPLIT_NEXT_ACTION
        )
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        text_char_count = _total_text_char_count(filtered_rows)
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
                next_action=_SPLIT_NEXT_ACTION,
            )

        return Result.success(
            OwnershipReportData(
                corp_code=corp_code,
                report_type=report.key,
                label=report.label,
                bgn_de=bgn_de,
                end_de=end_de,
                total_row_count=len(rows),
                returned_row_count=len(filtered_rows),
                rows=filtered_rows,
            ),
            warnings=warnings,
        )

    def _guard_report_type(self, report_type: str) -> GuardViolation | None:
        if report_type in self._registry:
            return None
        return GuardViolation(
            error_info(
                ErrorCode.INVALID_INPUT,
                "지원하지 않는 report_type 값입니다.",
                retryable=False,
                details={
                    "report_type": report_type,
                    "supported_report_types": _supported_report_types(self._registry),
                },
            ),
            next_action=_supported_report_types_next_action(self._registry),
        )


def _guard_date_range(bgn_de: str, end_de: str) -> GuardViolation | None:
    """Reject a malformed or inverted receipt-date range before any network call.

    Both bgn_de and end_de are optional (empty string means "no bound"), but
    a value that is supplied must be 8 ASCII digits, and when both are
    supplied bgn_de must not come after end_de.
    """
    for field_name, value in (("bgn_de", bgn_de), ("end_de", end_de)):
        if value and _DATE_PATTERN.match(value) is None:
            return GuardViolation(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "접수일 형식이 올바르지 않습니다.",
                    retryable=False,
                    details={"field": field_name, "value": value},
                ),
                next_action=_DATE_FORMAT_NEXT_ACTION,
            )
    if bgn_de and end_de and bgn_de > end_de:
        return GuardViolation(
            error_info(
                ErrorCode.INVALID_INPUT,
                "bgn_de가 end_de보다 늦습니다.",
                retryable=False,
                details={"bgn_de": bgn_de, "end_de": end_de},
            ),
            next_action=_DATE_ORDER_NEXT_ACTION,
        )
    return None


def _row_in_range(row: JsonObject, bgn_de: str, end_de: str) -> bool:
    """Keep a row unless its receipt date falls outside [bgn_de, end_de].

    A row whose receipt date cannot be determined is always kept: silently
    dropping an undateable row would violate the never-truncate policy that
    guard_row_count enforces on the other side of this filter.
    """
    if not bgn_de and not end_de:
        return True
    receipt_date = _row_receipt_date(row)
    if receipt_date is None:
        return True
    if bgn_de and receipt_date < bgn_de:
        return False
    return not (end_de and receipt_date > end_de)


def _row_receipt_date(row: JsonObject) -> str | None:
    """Extract a row's YYYYMMDD receipt date from rcept_dt, else rcept_no.

    A value that does not normalize to eight digits is treated as absent —
    comparing malformed text lexicographically against YYYYMMDD bounds would
    silently drop the row instead of keeping it.
    """
    rcept_dt = row.get("rcept_dt")
    if isinstance(rcept_dt, str):
        normalized = rcept_dt.replace("-", "")
        if _DATE_PATTERN.match(normalized) is not None:
            return normalized
    rcept_no = row.get("rcept_no")
    if isinstance(rcept_no, str) and _DATE_PATTERN.match(rcept_no[:8]) is not None:
        return rcept_no[:8]
    return None


def _empty_warning(report_type: str) -> WarningInfo:
    return WarningInfo(
        code=WarningCode.PARTIAL_COLLECTION,
        message="해당 report_type에서 지분공시 정보를 찾지 못했습니다.",
        details={"report_type": report_type},
    )


def _supported_report_types(
    registry: Mapping[str, OwnershipReport],
) -> list[JsonValue]:
    return [
        {"report_type": report.key, "label": report.label}
        for report in registry.values()
    ]


def _supported_report_types_next_action(registry: Mapping[str, OwnershipReport]) -> str:
    return f"{', '.join(registry)} 중 하나를 report_type에 지정하세요."


# Mirrors domains/report_topics.py's _total_text_char_count /
# _json_text_char_count. Both are module-private helpers of their own
# registry service, so this is duplicated rather than imported.
def _total_text_char_count(rows: tuple[JsonObject, ...]) -> int:
    return sum(_json_text_char_count(row) for row in rows)


def _json_text_char_count(value: JsonValue) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_json_text_char_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_json_text_char_count(item) for item in value)
    return 0
