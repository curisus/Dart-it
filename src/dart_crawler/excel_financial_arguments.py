from typing import Final

from pydantic import Field, field_validator

from dart_crawler.domains.query_guards import (
    MIN_BSNS_YEAR,
    VALID_FS_DIVS,
    VALID_IDX_CL_CODES,
    VALID_REPRT_CODES,
)
from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_argument_validation_primitives import (
    JsonStringTuple,
    argument_validation_failure,
    validate_corp_code,
    validate_unique,
)

_REPRT_CODES: Final = frozenset(VALID_REPRT_CODES)
_FS_DIVS: Final = frozenset(VALID_FS_DIVS)
_INDEX_CODES: Final = frozenset(VALID_IDX_CL_CODES)


def _validate_registered(value: str, registry: frozenset[str]) -> str:
    if value in registry:
        return value
    return argument_validation_failure("registry_value", "unregistered value")


class FinancialPeriodArguments(StrictExcelArguments):
    corp_code: str
    bsns_year: int = Field(ge=MIN_BSNS_YEAR, strict=True)
    reprt_code: str

    validate_corp_code_field = field_validator("corp_code")(validate_corp_code)

    @field_validator("reprt_code")
    @classmethod
    def validate_reprt_code(cls, value: str) -> str:
        return _validate_registered(value, _REPRT_CODES)


class GetFinancialStatementsArguments(FinancialPeriodArguments):
    fs_div: str = "CFS"

    @field_validator("fs_div")
    @classmethod
    def validate_fs_div(cls, value: str) -> str:
        return _validate_registered(value, _FS_DIVS)


class CompanySelectionArguments(StrictExcelArguments):
    corp_codes: JsonStringTuple = Field(min_length=1, max_length=100)
    bsns_year: int = Field(ge=MIN_BSNS_YEAR, strict=True)
    reprt_code: str

    validate_unique_corp_codes = field_validator("corp_codes")(validate_unique)

    @field_validator("corp_codes")
    @classmethod
    def validate_corp_codes(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(validate_corp_code(value) for value in values)

    @field_validator("reprt_code")
    @classmethod
    def validate_reprt_code(cls, value: str) -> str:
        return _validate_registered(value, _REPRT_CODES)


class GetMajorAccountsArguments(CompanySelectionArguments):
    pass


class GetFinancialIndicatorsArguments(CompanySelectionArguments):
    idx_cl_code: str

    @field_validator("idx_cl_code")
    @classmethod
    def validate_idx_cl_code(cls, value: str) -> str:
        return _validate_registered(value, _INDEX_CODES)
