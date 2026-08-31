from collections.abc import Callable
from typing import ClassVar, Final

from pydantic import field_validator

from dart_crawler.domain import ReportKind
from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_argument_validation_primitives import (
    argument_validation_failure,
    validate_corp_code,
    validate_rcept_no,
)

_REPORT_KINDS: Final = frozenset(kind.value for kind in ReportKind)


class SearchCompaniesArguments(StrictExcelArguments):
    company_query: str
    report_kind: str | None = None

    @field_validator("report_kind")
    @classmethod
    def validate_report_kind(cls, value: str | None) -> str | None:
        if value is None or value in _REPORT_KINDS:
            return value
        return argument_validation_failure(
            "report_kind",
            "unregistered report kind",
        )


class ListReportFilingsArguments(StrictExcelArguments):
    corp_code: str
    report_kind: str

    validate_corp_code_field: ClassVar[Callable[[str], str]] = field_validator(
        "corp_code",
    )(validate_corp_code)

    @field_validator("report_kind")
    @classmethod
    def validate_report_kind(cls, value: str) -> str:
        if value in _REPORT_KINDS:
            return value
        return argument_validation_failure(
            "report_kind",
            "unregistered report kind",
        )


class ListReportAttachmentsArguments(StrictExcelArguments):
    rcept_no: str

    validate_rcept_no_field: ClassVar[Callable[[str], str]] = field_validator(
        "rcept_no",
    )(validate_rcept_no)


class GetCompanyProfileArguments(StrictExcelArguments):
    corp_code: str

    validate_corp_code_field: ClassVar[Callable[[str], str]] = field_validator(
        "corp_code",
    )(validate_corp_code)
