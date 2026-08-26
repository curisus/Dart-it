from typing import Final, Self

from pydantic import Field, field_validator, model_validator

from dart_crawler.domains.material_events import MATERIAL_EVENTS
from dart_crawler.domains.ownership import OWNERSHIP_REPORTS
from dart_crawler.domains.query_guards import (
    MIN_BSNS_YEAR,
    VALID_REPRT_CODES,
)
from dart_crawler.domains.registration_statements import REGISTRATION_STATEMENTS
from dart_crawler.domains.report_topics import REPORT_TOPICS
from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_argument_validation_primitives import (
    JsonStringTuple,
    argument_validation_failure,
    validate_corp_code,
    validate_date_order,
    validate_optional_date,
    validate_required_date,
    validate_unique,
)

_REPRT_CODES: Final = frozenset(VALID_REPRT_CODES)


def _validate_registered(value: str, registry: frozenset[str]) -> str:
    if value in registry:
        return value
    return argument_validation_failure("registry_value", "unregistered value")


class GetReportTopicsArguments(StrictExcelArguments):
    corp_code: str
    bsns_year: int = Field(ge=MIN_BSNS_YEAR, strict=True)
    reprt_code: str
    topics: JsonStringTuple = Field(
        min_length=1,
        max_length=len(REPORT_TOPICS),
    )

    validate_corp_code_field = field_validator("corp_code")(validate_corp_code)
    validate_unique_topics = field_validator("topics")(validate_unique)

    @field_validator("reprt_code")
    @classmethod
    def validate_reprt_code(cls, value: str) -> str:
        return _validate_registered(value, _REPRT_CODES)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if all(value in REPORT_TOPICS for value in values):
            return values
        return argument_validation_failure("topic", "unregistered topic")


class GetOwnershipReportsArguments(StrictExcelArguments):
    corp_code: str
    report_type: str
    bgn_de: str = ""
    end_de: str = ""

    validate_corp_code_field = field_validator("corp_code")(validate_corp_code)
    validate_bgn_de = field_validator("bgn_de")(validate_optional_date)
    validate_end_de = field_validator("end_de")(validate_optional_date)

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, value: str) -> str:
        return _validate_registered(value, frozenset(OWNERSHIP_REPORTS))

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        validate_date_order(self.bgn_de, self.end_de)
        return self


class GetMaterialEventsArguments(StrictExcelArguments):
    corp_code: str
    event_types: JsonStringTuple = Field(
        min_length=1,
        max_length=len(MATERIAL_EVENTS),
    )
    bgn_de: str
    end_de: str

    validate_corp_code_field = field_validator("corp_code")(validate_corp_code)
    validate_unique_event_types = field_validator("event_types")(validate_unique)
    validate_bgn_de = field_validator("bgn_de")(validate_required_date)
    validate_end_de = field_validator("end_de")(validate_required_date)

    @field_validator("event_types")
    @classmethod
    def validate_event_types(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if all(value in MATERIAL_EVENTS for value in values):
            return values
        return argument_validation_failure(
            "event_type",
            "unregistered event type",
        )

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        validate_date_order(self.bgn_de, self.end_de)
        return self


class GetRegistrationStatementsArguments(StrictExcelArguments):
    corp_code: str
    stmt_type: str
    bgn_de: str
    end_de: str

    validate_corp_code_field = field_validator("corp_code")(validate_corp_code)
    validate_bgn_de = field_validator("bgn_de")(validate_required_date)
    validate_end_de = field_validator("end_de")(validate_required_date)

    @field_validator("stmt_type")
    @classmethod
    def validate_stmt_type(cls, value: str) -> str:
        return _validate_registered(value, frozenset(REGISTRATION_STATEMENTS))

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        validate_date_order(self.bgn_de, self.end_de)
        return self
