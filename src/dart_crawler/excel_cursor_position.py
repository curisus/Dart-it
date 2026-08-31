from __future__ import annotations

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from dart_crawler.excel_contract_errors import excel_failure
from dart_crawler.excel_cursor import ExcelCursorPayload
from dart_crawler.result import Result

_FINGERPRINT_PATTERN: Final = r"^[0-9a-f]{64}$"


class CursorDatasetState(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    source_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    total_row_count: int = Field(ge=0)


def validate_cursor_after_query(
    payload: ExcelCursorPayload,
    state: CursorDatasetState,
) -> Result[ExcelCursorPayload]:
    if payload.source_fingerprint != state.source_fingerprint:
        return excel_failure("source_changed")
    if (
        payload.offset == 0
        or payload.page_index == 0
        or payload.offset >= state.total_row_count
    ):
        return excel_failure("cursor_position_invalid")
    return Result[ExcelCursorPayload].success(payload)
