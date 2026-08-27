from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum, unique
from typing import ClassVar, Final, Literal, assert_never

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from dart_crawler.result import JsonObject, WarningInfo

EXCEL_SCHEMA_VERSION: Final = 1
EXCEL_CURSOR_VERSION: Final = 1
EXCEL_PAGE_BUDGET_BYTES: Final = 3_500_000
DEFAULT_EXCEL_PAGE_SIZE: Final = 1_000
MAX_EXCEL_PAGE_SIZE: Final = 1_000
MAX_EXCEL_PAGE_ROWS: Final = MAX_EXCEL_PAGE_SIZE
_FINGERPRINT_PATTERN: Final = r"^[0-9a-f]{64}$"
_OPTIONAL_FINGERPRINT_PATTERN: Final = r"^(?:|[0-9a-f]{64})$"

type ExcelScalar = str | int | float | bool | None
type ExcelRow = dict[str, ExcelScalar]


@unique
class ExcelDataDomain(StrEnum):
    SEARCH_COMPANIES = "search_companies"
    LIST_REPORT_FILINGS = "list_report_filings"
    LIST_REPORT_ATTACHMENTS = "list_report_attachments"
    LIST_REPORT_SECTIONS = "list_report_sections"
    GET_REPORT_SECTIONS = "get_report_sections"
    GET_FINANCIAL_STATEMENTS = "get_financial_statements"
    GET_MAJOR_ACCOUNTS = "get_major_accounts"
    GET_FINANCIAL_INDICATORS = "get_financial_indicators"
    GET_REPORT_TOPICS = "get_report_topics"
    GET_COMPANY_PROFILE = "get_company_profile"
    GET_OWNERSHIP_REPORTS = "get_ownership_reports"
    GET_MATERIAL_EVENTS = "get_material_events"
    GET_REGISTRATION_STATEMENTS = "get_registration_statements"


class ExcelProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    source: str = "dart"
    source_fingerprint: str = Field(default="", pattern=_OPTIONAL_FINGERPRINT_PATTERN)


class ExcelLoadRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    domain: ExcelDataDomain
    arguments: JsonObject
    page_size: int = Field(
        default=DEFAULT_EXCEL_PAGE_SIZE,
        ge=1,
        le=MAX_EXCEL_PAGE_SIZE,
        strict=True,
    )
    cursor: str | None = None


class ExcelPage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
    )

    schema_version: Literal[1] = EXCEL_SCHEMA_VERSION
    domain: ExcelDataDomain
    request_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    source_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    dataset_id: str = Field(default="", pattern=_OPTIONAL_FINGERPRINT_PATTERN)
    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]
    warnings: tuple[WarningInfo, ...] = ()
    provenance: ExcelProvenance = Field(default_factory=ExcelProvenance)
    total_rows: int = Field(ge=0, strict=True)
    offset: int = Field(ge=0, strict=True)
    page_index: int = Field(default=0, ge=0, strict=True)
    page_size: int = Field(ge=1, le=MAX_EXCEL_PAGE_SIZE, strict=True)
    returned_rows: int = Field(ge=0, strict=True)
    next_cursor: str | None = None

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(
        cls,
        dataset_id: str,
        info: ValidationInfo,
    ) -> str:
        domain = info.data.get("domain")
        request_fingerprint = info.data.get("request_fingerprint")
        source_fingerprint = info.data.get("source_fingerprint")
        if not isinstance(domain, ExcelDataDomain) or not isinstance(
            request_fingerprint,
            str,
        ) or not isinstance(
            source_fingerprint,
            str,
        ):
            return dataset_id
        expected = _dataset_id(domain, request_fingerprint, source_fingerprint)
        if dataset_id not in ("", expected):
            msg = "Excel page dataset id does not match its fingerprints"
            raise ValueError(msg)
        return expected

    @field_validator("rows")
    @classmethod
    def validate_rows(
        cls,
        rows: tuple[ExcelRow, ...],
        info: ValidationInfo,
    ) -> tuple[ExcelRow, ...]:
        raw_columns = info.data.get("columns")
        if not isinstance(raw_columns, tuple):
            return rows
        columns = tuple(
            column for column in raw_columns if isinstance(column, str)
        )
        if len(columns) != len(raw_columns):
            msg = "Excel page columns must be strings"
            raise ValueError(msg)
        return _normalize_rows(columns, rows)

    @field_validator("provenance")
    @classmethod
    def validate_provenance(
        cls,
        provenance: ExcelProvenance,
        info: ValidationInfo,
    ) -> ExcelProvenance:
        source_fingerprint = info.data.get("source_fingerprint")
        if not isinstance(source_fingerprint, str):
            return provenance
        if provenance.source_fingerprint == "":
            return ExcelProvenance(
                source=provenance.source,
                source_fingerprint=source_fingerprint,
            )
        if provenance.source_fingerprint != source_fingerprint:
            msg = "Excel page provenance does not match source fingerprint"
            raise ValueError(msg)
        return provenance

    @model_validator(mode="after")
    def validate_contract(self) -> ExcelPage:
        if self.returned_rows != len(self.rows):
            msg = "Excel page row count does not match rows"
            raise ValueError(msg)
        if self.returned_rows > self.page_size:
            msg = "Excel page row count exceeds page_size"
            raise ValueError(msg)
        end_offset = self.offset + self.returned_rows
        if self.total_rows < end_offset:
            msg = "Excel page total row count is below the returned range"
            raise ValueError(msg)
        has_remaining_rows = end_offset < self.total_rows
        if (self.next_cursor is not None) != has_remaining_rows:
            msg = "Excel page cursor presence does not match remaining rows"
            raise ValueError(msg)
        return self


def _normalize_rows(
    columns: tuple[str, ...],
    rows: tuple[ExcelRow, ...],
) -> tuple[ExcelRow, ...]:
    if len(set(columns)) != len(columns):
        msg = "Excel page columns must be unique"
        raise ValueError(msg)
    normalized: list[ExcelRow] = []
    for row in rows:
        if set(row) != set(columns):
            msg = "Excel page rows must match the ordered columns"
            raise ValueError(msg)
        for value in row.values():
            match value:
                case float() as number:
                    if not math.isfinite(number):
                        msg = "Excel page scalar floats must be finite"
                        raise ValueError(msg)
                case str() | int() | bool() | None:
                    pass
                case unreachable:
                    assert_never(unreachable)
        normalized.append({column: row[column] for column in columns})
    return tuple(normalized)


def _dataset_id(
    domain: ExcelDataDomain,
    request_fingerprint: str,
    source_fingerprint: str,
) -> str:
    value: JsonObject = {
        "domain": domain.value,
        "request_fingerprint": request_fingerprint,
        "schema_version": EXCEL_SCHEMA_VERSION,
        "source_fingerprint": source_fingerprint,
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: JsonObject) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
