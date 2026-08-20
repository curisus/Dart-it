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


class DartRowsResponse[RowT](BaseModel):
    """Generic OpenDART envelope for endpoints that return rows under `list`."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: str
    message: str
    list: tuple[RowT, ...] = ()


DartListResponse = DartRowsResponse[DartListRow]


class DartGroup[RowT](BaseModel):
    """One titled OpenDART group containing a required row list."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str
    list: tuple[RowT, ...]


class DartGroupsResponse[RowT](BaseModel):
    """OpenDART envelope for endpoints that return titled row groups."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: str
    message: str
    group: tuple[DartGroup[RowT], ...] = ()


class FinancialAccount(BaseModel):
    """One row from the OpenDART full-account financial API."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    # fnlttSinglAcntAll rows do not echo the fs_div request parameter,
    # so the field must stay optional or every real payload fails to parse.
    fs_div: str = ""
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
    rcept_no: str = ""
    corp_code: str = ""
    sj_nm: str = ""
    fs_nm: str = ""
    account_detail: str = ""
    thstrm_nm: str = ""
    frmtrm_nm: str = ""
    frmtrm_q_nm: str = ""
    bfefrmtrm_nm: str = ""
    bfefrmtrm_amount: str = ""
    ord: str = ""


FinancialAccountResponse = DartRowsResponse[FinancialAccount]


class MajorAccountRow(BaseModel):
    """One row from the OpenDART major-account financial API (DS003)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    rcept_no: str = ""
    reprt_code: str
    bsns_year: str
    corp_code: str = ""
    stock_code: str = ""
    fs_div: str
    fs_nm: str = ""
    sj_div: str
    sj_nm: str = ""
    account_nm: str
    thstrm_nm: str = ""
    thstrm_dt: str = ""
    thstrm_amount: str = ""
    thstrm_add_amount: str = ""
    frmtrm_nm: str = ""
    frmtrm_dt: str = ""
    frmtrm_amount: str = ""
    frmtrm_add_amount: str = ""
    bfefrmtrm_nm: str = ""
    bfefrmtrm_dt: str = ""
    bfefrmtrm_amount: str = ""
    ord: str = ""
    currency: str = ""


class FinancialIndexRow(BaseModel):
    """One row from the OpenDART financial-index API (DS003)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    bsns_year: str
    corp_code: str = ""
    stock_code: str = ""
    stlm_dt: str = ""
    idx_cl_code: str = ""
    idx_cl_nm: str = ""
    idx_nm: str = ""
    idx_val: str = ""


class CompanyProfile(BaseModel):
    """OpenDART DS001 company master-data envelope (company.json).

    Unlike the row endpoints, company.json returns its payload fields at the
    top level beside status/message rather than under a `list`, so it does
    not fit the DartRowsResponse shape.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: str
    message: str
    corp_code: str = ""
    corp_name: str = ""
    corp_name_eng: str = ""
    stock_name: str = ""
    stock_code: str = ""
    ceo_nm: str = ""
    corp_cls: str = ""
    jurir_no: str = ""
    bizr_no: str = ""
    adres: str = ""
    hm_url: str = ""
    ir_url: str = ""
    phn_no: str = ""
    fax_no: str = ""
    induty_code: str = ""
    est_dt: str = ""
    acc_mt: str = ""
