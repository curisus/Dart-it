"""Validated domain models for companies, filings, and attachments."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import assert_never

from pydantic import BaseModel, ConfigDict, Field


@unique
class ReportKind(StrEnum):
    """Supported report families."""

    AUDIT = "audit"
    QUARTERLY_REVIEW = "quarterly_review"
    HALF_YEAR_REVIEW = "half_year_review"


@unique
class ReportPeriod(StrEnum):
    """Period labels shown by the filing list."""

    FY = "FY"
    FIRST_QUARTER = "1Q"
    HALF_YEAR = "HY"
    THIRD_QUARTER = "3Q"


@unique
class Market(StrEnum):
    """DART market classification values."""

    KOSPI = "Y"
    KOSDAQ = "K"
    KONEX = "N"
    OTHER = "E"

    @property
    def label(self) -> str:
        """Return the market label shown to an MCP client."""
        match self:
            case Market.KOSPI:
                return "유가증권"
            case Market.KOSDAQ:
                return "코스닥"
            case Market.KONEX:
                return "코넥스"
            case Market.OTHER:
                return "기타"
            case unreachable:
                assert_never(unreachable)


@unique
class MatchConfidence(StrEnum):
    """How closely a company search result matched the query."""

    EXACT = "exact"
    PREFIX = "prefix"
    CONTAINS = "contains"
    ALIAS = "alias"
    SIMILAR = "similar"


class Company(BaseModel):
    """Company row returned by company search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_name: str = Field(min_length=1)
    corp_code: str = Field(pattern=r"^\d{8}$")
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    market: Market
    ranking: int = Field(ge=1, le=5)
    match_confidence: MatchConfidence


class Filing(BaseModel):
    """Representative filing after correction-series consolidation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str = Field(pattern=r"^\d{8}$")
    company_name: str
    report_kind: ReportKind
    report_period: ReportPeriod
    fiscal_year: int = Field(ge=1900, le=9999)
    report_name: str
    rcept_no: str = Field(pattern=r"^\d{14}$")
    receipt_date: str = Field(pattern=r"^\d{8}$")
    correction_chain: tuple[str, ...] = ()
    withdrawn: bool = False


class Attachment(BaseModel):
    """Selectable report attachment from a ZIP or DART viewer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: str = Field(pattern=r"^(opendart|viewer):\d{14}:.+")
    rcept_no: str = Field(pattern=r"^\d{14}$")
    title: str
    source: str
    standalone: bool
    filename: str | None = None
    dcm_no: str | None = None
