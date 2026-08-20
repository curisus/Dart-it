"""DS006 securities registration statement groups for one statement type."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.api_models import DartGroup
from dart_crawler.domains.query_guards import (
    GuardViolation,
    guard_corp_code,
    guard_required_date_range,
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

_SPLIT_NEXT_ACTION: Final = "기간을 좁혀 다시 호출하세요."
_SUPPORTED_STMT_TYPES_NEXT_ACTION: Final = (
    "지원 stmt_type 목록은 오류 details의 supported_stmt_types를 확인하세요."
)

REGISTRATION_STATEMENTS: Final = as_registry(
    RegistryEntry("equity_securities", "estkRs", "증권신고서(지분증권)"),
    RegistryEntry("debt_securities", "bdRs", "증권신고서(채무증권)"),
    RegistryEntry("depositary_receipts", "stkdpRs", "증권신고서(증권예탁증권)"),
    RegistryEntry("merger", "mgRs", "증권신고서(합병)"),
    RegistryEntry(
        "stock_exchange_transfer",
        "extrRs",
        "증권신고서(주식의포괄적교환·이전)",
    ),
    RegistryEntry("division", "dvRs", "증권신고서(분할)"),
    noun="registration statement",
)


class RegistrationStatementSource(Protocol):
    """OpenDART capability required by the DS006 domain service."""

    def fetch_registration_statement_groups(
        self,
        endpoint: str,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[tuple[DartGroup[JsonObject], ...]]:
        """Fetch one DS006 endpoint's titled groups."""
        raise NotImplementedError


class RegistrationStatementGroup(BaseModel):
    """One source group from a DS006 response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    row_count: int
    rows: tuple[JsonObject, ...]


class RegistrationStatementData(BaseModel):
    """DS006 groups for one company, one date range, and one stmt_type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str
    stmt_type: str
    label: str
    bgn_de: str
    end_de: str
    returned_group_count: int
    returned_row_count: int
    groups: tuple[RegistrationStatementGroup, ...]


class RegistrationStatementService:
    """Validate, fetch, and size-guard one DS006 stmt_type request."""

    def __init__(
        self,
        source: RegistrationStatementSource,
        *,
        registry: Mapping[str, RegistryEntry] = REGISTRATION_STATEMENTS,
    ) -> None:
        """Create a DS006 service backed by an OpenDART source."""
        self._source = source
        self._registry = registry

    def get(
        self,
        corp_code: str,
        stmt_type: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[RegistrationStatementData]:
        """Return DS006 groups for one supported stmt_type."""
        violation = (
            guard_corp_code(corp_code)
            or guard_required_date_range(bgn_de, end_de)
            or self._guard_stmt_type(stmt_type)
        )
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        statement = self._registry[stmt_type]
        fetched = self._source.fetch_registration_statement_groups(
            statement.endpoint, corp_code, bgn_de, end_de
        )
        if not fetched.ok or fetched.data is None:
            if fetched.error is not None and fetched.error.code is ErrorCode.NOT_FOUND:
                source_groups: tuple[DartGroup[JsonObject], ...] = ()
            else:
                return Result.failure(
                    fetched.error
                    if fetched.error is not None
                    else error_info(
                        ErrorCode.UPSTREAM_UNAVAILABLE,
                        "OpenDART 증권신고서 정보를 수집할 수 없습니다.",
                        retryable=True,
                    ),
                    warnings=fetched.warnings,
                    next_action=fetched.next_action,
                )
        else:
            source_groups = fetched.data

        groups = tuple(
            RegistrationStatementGroup(
                title=group.title,
                row_count=len(group.list),
                rows=group.list,
            )
            for group in source_groups
        )
        total_row_count = sum(group.row_count for group in groups)
        row_violation = guard_row_count(total_row_count, next_action=_SPLIT_NEXT_ACTION)
        if row_violation is not None:
            return Result.failure(
                row_violation.error,
                next_action=row_violation.next_action,
            )

        text_char_count = _total_text_char_count(groups)
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

        warnings: tuple[WarningInfo, ...] = ()
        if total_row_count == 0:
            warnings = (
                WarningInfo(
                    code=WarningCode.PARTIAL_COLLECTION,
                    message="요청한 stmt_type의 증권신고서 주요정보를 찾지 못했습니다.",
                    details={"empty_stmt_type": statement.key},
                ),
            )

        return Result.success(
            RegistrationStatementData(
                corp_code=corp_code,
                stmt_type=statement.key,
                label=statement.label,
                bgn_de=bgn_de,
                end_de=end_de,
                returned_group_count=len(groups),
                returned_row_count=total_row_count,
                groups=groups,
            ),
            warnings=warnings,
        )

    def _guard_stmt_type(self, stmt_type: str) -> GuardViolation | None:
        """Reject unsupported DS006 stmt_type values before source calls."""
        if stmt_type in self._registry:
            return None
        return GuardViolation(
            error_info(
                ErrorCode.INVALID_INPUT,
                "지원하지 않는 stmt_type 값입니다.",
                retryable=False,
                details={
                    "stmt_type": stmt_type,
                    "supported_stmt_types": _supported_stmt_types(self._registry),
                },
            ),
            next_action=_SUPPORTED_STMT_TYPES_NEXT_ACTION,
        )


def _supported_stmt_types(registry: Mapping[str, RegistryEntry]) -> list[JsonValue]:
    """Return supported stmt_type values in a JSON-serializable shape."""
    return [
        {"stmt_type": statement.key, "label": statement.label}
        for statement in registry.values()
    ]


def _total_text_char_count(groups: tuple[RegistrationStatementGroup, ...]) -> int:
    """Count text characters across all returned DS006 row values."""
    return sum(_json_text_char_count(row) for group in groups for row in group.rows)


def _json_text_char_count(value: JsonValue) -> int:
    """Count text characters recursively inside one JSON value."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_json_text_char_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_json_text_char_count(item) for item in value)
    return 0
