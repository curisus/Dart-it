from typing import assert_never

from dart_crawler.excel_row_normalization import ExcelSourceValue, SourcePairs
from dart_crawler.result import JsonObject, JsonValue


def json_object_pairs(value: JsonObject) -> SourcePairs:
    return tuple(
        (name, json_value_to_source(item)) for name, item in value.items()
    )


def json_value_to_source(value: JsonValue) -> ExcelSourceValue:
    match value:
        case bool() as boolean:
            return boolean
        case int() as integer:
            return integer
        case float() as number:
            return number
        case str() as text:
            return text
        case None:
            return None
        case list() as items:
            return [json_value_to_source(item) for item in items]
        case dict() as mapping:
            return {
                name: json_value_to_source(item)
                for name, item in mapping.items()
            }
        case unreachable:
            assert_never(unreachable)
