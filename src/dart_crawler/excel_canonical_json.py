import json

from dart_crawler.result import JsonValue


def canonical_json_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_text(value: JsonValue) -> str:
    return canonical_json_bytes(value).decode("utf-8")
