from collections.abc import Callable
from typing import ClassVar, Final, Self

from pydantic import Field, field_validator, model_validator

from dart_crawler.document_model import SectionKind
from dart_crawler.excel_argument_base import StrictExcelArguments
from dart_crawler.excel_argument_validation_primitives import (
    JsonStringTuple,
    argument_validation_failure,
    validate_rcept_no,
    validate_section_id,
    validate_unique,
)
from dart_crawler.section_models import STATEMENTS_ALIAS

_SECTION_KINDS: Final = frozenset(
    (kind.value for kind in SectionKind),
) | {STATEMENTS_ALIAS}


class ListReportSectionsArguments(StrictExcelArguments):
    rcept_no: str
    attachment_id: str = Field(min_length=1)

    validate_rcept_no_field: ClassVar[Callable[[str], str]] = field_validator(
        "rcept_no",
    )(validate_rcept_no)


class GetReportSectionsArguments(StrictExcelArguments):
    rcept_no: str
    attachment_id: str = Field(min_length=1)
    section_ids: JsonStringTuple = ()
    section_kinds: JsonStringTuple = ()

    validate_rcept_no_field: ClassVar[Callable[[str], str]] = field_validator(
        "rcept_no",
    )(validate_rcept_no)
    validate_section_ids: ClassVar[
        Callable[[tuple[str, ...]], tuple[str, ...]]
    ] = field_validator("section_ids")(validate_unique)
    validate_section_kinds_unique: ClassVar[
        Callable[[tuple[str, ...]], tuple[str, ...]]
    ] = field_validator("section_kinds")(
        validate_unique
    )

    @field_validator("section_ids")
    @classmethod
    def validate_section_id_values(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(validate_section_id(value) for value in values)

    @field_validator("section_kinds")
    @classmethod
    def validate_section_kind_values(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if all(value in _SECTION_KINDS for value in values):
            return values
        return argument_validation_failure(
            "section_kind",
            "unregistered section kind",
        )

    @model_validator(mode="after")
    def require_selector(self) -> Self:
        if self.section_ids or self.section_kinds:
            return self
        return argument_validation_failure(
            "section_selector",
            "at least one section selector is required",
        )
