"""Pydantic models for OpenDART JSON responses."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DartListRow(BaseModel):
    """One row from the OpenDART disclosure search API."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    corp_cls: str = "E"
    corp_name: str
    corp_code: str = Field(pattern=r"^\d{8}$")
    stock_code: str | None = None
    report_nm: str
    rcept_no: str = Field(pattern=r"^\d{14}$")
    rcept_dt: str = Field(pattern=r"^\d{8}$")
    rm: str = ""

    @field_validator("stock_code", mode="before")
    @classmethod
    def empty_stock_code_is_none(cls, value: str | None) -> str | None:
        """Normalize DART's empty stock-code field."""
        return value or None


class DartListResponse(BaseModel):
    """OpenDART disclosure search response."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: str
    message: str
    list: tuple[DartListRow, ...] = ()


class FinancialAccount(BaseModel):
    """One row from the OpenDART full-account financial API."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    fs_div: str
    sj_div: str
    bsns_year: str
    reprt_code: str
    account_id: str
    account_nm: str
    thstrm_amount: str = ""
    thstrm_add_amount: str = ""
    frmtrm_amount: str = ""
    frmtrm_q_amount: str = ""
    frmtrm_add_amount: str = ""
    currency: str = ""


class FinancialAccountResponse(BaseModel):
    """OpenDART full-account response."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: str
    message: str
    list: tuple[FinancialAccount, ...] = ()
