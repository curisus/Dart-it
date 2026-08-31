from pydantic import BaseModel, TypeAdapter

from dart_crawler.result import JsonObject

_JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


def model_json_object(model: BaseModel) -> JsonObject:
    return _JSON_OBJECT_ADAPTER.validate_python(
        model.model_dump(
            mode="json",
            by_alias=False,
            exclude_unset=False,
            exclude_defaults=False,
            exclude_none=False,
        )
    )


def model_columns(model_type: type[BaseModel]) -> tuple[str, ...]:
    return tuple(model_type.model_fields)
