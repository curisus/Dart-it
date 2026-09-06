from __future__ import annotations

import math
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dart_crawler.excel_page_models import (
    EXCEL_SCHEMA_VERSION,
    ExcelDataDomain,
    ExcelRow,
)
from dart_crawler.result import JsonObject, WarningInfo

_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


class NormalizedExcelProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    domain: ExcelDataDomain
    source: Literal["dart"] = "dart"
    source_rows: int = Field(ge=0, strict=True)
    normalized_rows: int = Field(ge=0, strict=True)
    source_groups: int = Field(default=0, ge=0, strict=True)
    source_sections: int = Field(default=0, ge=0, strict=True)
    source_blocks: int = Field(default=0, ge=0, strict=True)
    reported_rows: int | None = Field(default=None, ge=0, strict=True)
    reported_total_rows: int | None = Field(default=None, ge=0, strict=True)
    reported_groups: int | None = Field(default=None, ge=0, strict=True)
    source_sha256: str | None = None
    parser_version: str | None = None
    source_type: str | None = None
    report_title: str | None = None
    coverage_complete: bool | None = None


class NormalizedExcelDataset(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )

    schema_version: Literal[1] = EXCEL_SCHEMA_VERSION
    domain: ExcelDataDomain
    validated_arguments: JsonObject
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    source_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    dataset_id: str = Field(pattern=_FINGERPRINT_PATTERN)
    columns: tuple[str, ...]
    # Columns whose OpenDART text was read as a number; they carry a thousands
    # display format and both the writer and its validation derive it from here.
    numeric_columns: tuple[str, ...] = ()
    rows: tuple[ExcelRow, ...]
    warnings: tuple[WarningInfo, ...] = ()
    provenance: NormalizedExcelProvenance
    total_rows: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_dataset(self) -> NormalizedExcelDataset:
        if len(set(self.columns)) != len(self.columns):
            msg = "normalized columns must be unique"
            raise ValueError(msg)
        if not set(self.numeric_columns) <= set(self.columns):
            msg = "numeric columns must be a subset of columns"
            raise ValueError(msg)
        if self.total_rows != len(self.rows):
            msg = "normalized row count must match total_rows"
            raise ValueError(msg)
        if self.provenance.domain is not self.domain:
            msg = "normalized provenance domain must match"
            raise ValueError(msg)
        if self.provenance.normalized_rows != self.total_rows:
            msg = "normalized provenance count must match"
            raise ValueError(msg)
        for row in self.rows:
            if tuple(row) != self.columns:
                msg = "normalized row order must match columns"
                raise ValueError(msg)
            for value in row.values():
                match value:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
                    case float() as number if not math.isfinite(number):
                        msg = "normalized floats must be finite"
                        raise ValueError(msg)
                    case _:
                        pass
        return self
