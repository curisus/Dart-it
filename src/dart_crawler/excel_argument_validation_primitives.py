import re
from typing import Annotated, Final, Never

from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError

from dart_crawler.result import JsonValue

_CORP_CODE_PATTERN: Final = re.compile(r"^[0-9]{8}$")
_RCEPT_NO_PATTERN: Final = re.compile(r"^[0-9]{14}$")
_DATE_PATTERN: Final = re.compile(r"^[0-9]{8}$")
_SECTION_ID_PATTERN: Final = re.compile(r"^s[0-9]{3,}-[a-z_]+$")


def argument_validation_failure(code: str, message: str) -> Never:
    error = PydanticCustomError(code, message)
    raise error


def json_array_as_tuple(value: JsonValue) -> tuple[JsonValue, ...]:
    match value:
        case list() as items:
            return tuple(items)
        case _:
            argument_validation_failure("json_array", "value must be a JSON array")


JsonStringTuple = Annotated[
    tuple[str, ...],
    BeforeValidator(json_array_as_tuple),
]


def validate_corp_code(value: str) -> str:
    if _CORP_CODE_PATTERN.fullmatch(value) is not None:
        return value
    argument_validation_failure("corp_code", "corp_code must be 8 ASCII digits")


def validate_rcept_no(value: str) -> str:
    if _RCEPT_NO_PATTERN.fullmatch(value) is not None:
        return value
    argument_validation_failure("rcept_no", "rcept_no must be 14 ASCII digits")


def validate_required_date(value: str) -> str:
    if _DATE_PATTERN.fullmatch(value) is not None:
        return value
    argument_validation_failure("date", "date must be 8 ASCII digits")


def validate_optional_date(value: str) -> str:
    if value == "" or _DATE_PATTERN.fullmatch(value) is not None:
        return value
    argument_validation_failure("date", "date must be empty or 8 ASCII digits")


def validate_section_id(value: str) -> str:
    if _SECTION_ID_PATTERN.fullmatch(value) is not None:
        return value
    argument_validation_failure("section_id", "invalid section id")


def validate_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) == len(set(values)):
        return values
    argument_validation_failure("duplicate_selection", "values must be unique")


def validate_date_order(bgn_de: str, end_de: str) -> None:
    if bgn_de and end_de and bgn_de > end_de:
        argument_validation_failure("date_order", "bgn_de must not follow end_de")
