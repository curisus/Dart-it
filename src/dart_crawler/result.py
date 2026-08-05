"""Typed result envelopes exposed by the MCP boundary."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)
type JsonObject = dict[str, JsonValue]


@unique
class ErrorCode(StrEnum):
    """Stable failure codes returned by public tools."""

    CONFIG_ERROR = "CONFIG_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    UPSTREAM_AUTH = "UPSTREAM_AUTH"
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_LAYOUT_CHANGED = "UPSTREAM_LAYOUT_CHANGED"
    PARSE_FAILED = "PARSE_FAILED"
    CORE_STATEMENT_MISSING = "CORE_STATEMENT_MISSING"
    OUTPUT_WRITE_FAILED = "OUTPUT_WRITE_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@unique
class WarningCode(StrEnum):
    """Stable non-fatal warning codes returned by public tools."""

    PARTIAL_COLLECTION = "PARTIAL_COLLECTION"
    IMAGE_CONTENT_SKIPPED = "IMAGE_CONTENT_SKIPPED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    COMPARISON_UNAVAILABLE = "COMPARISON_UNAVAILABLE"
    FALLBACK_SOURCE_USED = "FALLBACK_SOURCE_USED"
    EXISTING_FILE_REUSED = "EXISTING_FILE_REUSED"


class ErrorInfo(BaseModel):
    """Structured failure data safe to serialize to an MCP client."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ErrorCode
    message: str
    retryable: bool
    details: JsonObject = Field(default_factory=dict)


class WarningInfo(BaseModel):
    """Structured non-fatal warning data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: WarningCode
    message: str
    details: JsonObject = Field(default_factory=dict)


T = TypeVar("T")


class Result[T](BaseModel):
    """Result envelope with one success or failure shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    data: T | None = None
    error: ErrorInfo | None = None
    warnings: tuple[WarningInfo, ...] = ()
    next_action: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> Result[T]:
        """Reject envelopes that mix success and failure fields."""
        if self.ok and (self.error is not None or self.data is None):
            msg = "successful results require data and cannot contain an error"
            raise ValueError(msg)
        if not self.ok and (self.error is None or self.data is not None):
            msg = "failed results require an error and cannot contain data"
            raise ValueError(msg)
        return self

    @classmethod
    def success(
        cls,
        data: T,
        *,
        warnings: tuple[WarningInfo, ...] = (),
        next_action: str | None = None,
    ) -> Result[T]:
        """Construct a successful envelope."""
        return cls(ok=True, data=data, warnings=warnings, next_action=next_action)

    @classmethod
    def failure(
        cls,
        error: ErrorInfo,
        *,
        warnings: tuple[WarningInfo, ...] = (),
        next_action: str | None = None,
    ) -> Result[T]:
        """Construct a failed envelope."""
        return cls(
            ok=False,
            error=error,
            warnings=warnings,
            next_action=next_action,
        )


def error_info(
    code: ErrorCode,
    message: str,
    *,
    retryable: bool,
    details: JsonObject | None = None,
) -> ErrorInfo:
    """Create a structured error without putting secrets in its details."""
    return ErrorInfo(
        code=code,
        message=message,
        retryable=retryable,
        details={} if details is None else details,
    )
