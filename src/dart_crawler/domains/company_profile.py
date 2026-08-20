"""DS001 company master-data lookup (company.json).

company.json returns one object per corp_code — names, CEO, registration
numbers, address, homepage, industry code, establishment date, and fiscal
month — rather than a list of rows, so this service has a single ``get``
instead of the row-collection guards financials.py and report_topics.py use.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from dart_crawler.api_models import CompanyProfile
from dart_crawler.domains.query_guards import guard_corp_code
from dart_crawler.result import ErrorCode, Result, error_info


class CompanyProfileSource(Protocol):
    """OpenDART capability required by the company-profile domain service."""

    def fetch_company_profile(self, corp_code: str) -> Result[CompanyProfile]:
        raise NotImplementedError


class CompanyProfileData(BaseModel):
    """One company's DART master-data fields, with status/message excluded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corp_code: str
    corp_name: str
    corp_name_eng: str
    stock_name: str
    stock_code: str
    ceo_nm: str
    corp_cls: str
    jurir_no: str
    bizr_no: str
    adres: str
    hm_url: str
    ir_url: str
    phn_no: str
    fax_no: str
    induty_code: str
    est_dt: str
    acc_mt: str


class CompanyProfileService:
    """Validate and fetch DS001 company master data for one corp_code."""

    def __init__(self, source: CompanyProfileSource) -> None:
        self._source = source

    def get(self, corp_code: str) -> Result[CompanyProfileData]:
        """Return one company's DART master-data fields."""
        violation = guard_corp_code(corp_code)
        if violation is not None:
            return Result.failure(violation.error, next_action=violation.next_action)

        fetched = self._source.fetch_company_profile(corp_code)
        if not fetched.ok or fetched.data is None:
            return Result.failure(
                fetched.error
                if fetched.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 기업개황을 수집할 수 없습니다.",
                    retryable=True,
                ),
                warnings=fetched.warnings,
                next_action=fetched.next_action,
            )

        profile = fetched.data
        return Result.success(
            CompanyProfileData(
                corp_code=profile.corp_code,
                corp_name=profile.corp_name,
                corp_name_eng=profile.corp_name_eng,
                stock_name=profile.stock_name,
                stock_code=profile.stock_code,
                ceo_nm=profile.ceo_nm,
                corp_cls=profile.corp_cls,
                jurir_no=profile.jurir_no,
                bizr_no=profile.bizr_no,
                adres=profile.adres,
                hm_url=profile.hm_url,
                ir_url=profile.ir_url,
                phn_no=profile.phn_no,
                fax_no=profile.fax_no,
                induty_code=profile.induty_code,
                est_dt=profile.est_dt,
                acc_mt=profile.acc_mt,
            ),
            warnings=fetched.warnings,
        )
