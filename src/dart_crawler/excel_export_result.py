from __future__ import annotations

from enum import StrEnum, unique
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from dart_crawler.result import (
    JsonObject,
    TypedResult,
    WarningCode,
    WarningInfo,
)


@unique
class ExcelCleanupWarningCode(StrEnum):
    OUTPUT_TEMP_CLEANUP_FAILED = "OUTPUT_TEMP_CLEANUP_FAILED"
    OUTPUT_LOCK_CLEANUP_FAILED = "OUTPUT_LOCK_CLEANUP_FAILED"


class ExcelExportWarningInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    code: WarningCode | ExcelCleanupWarningCode
    message: str
    details: JsonObject = Field(default_factory=dict)


class Result[T](TypedResult[T, ExcelExportWarningInfo]):
    """Result boundary used only by the local query-to-XLSX tool."""


def export_warning_from_core(warning: WarningInfo) -> ExcelExportWarningInfo:
    return ExcelExportWarningInfo(
        code=warning.code,
        message=warning.message,
        details=warning.details,
    )
