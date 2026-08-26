import json

from mcp_types import TextContent
from pydantic import TypeAdapter

from dart_crawler.excel_page_models import ExcelDataDomain, ExcelPage, ExcelRow
from dart_crawler.mcp_wire import (
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    WIRE_REQUEST_ID,
    WireProfile,
    excel_result_to_call_tool_result,
    measure_excel_result_wire,
    measure_excel_schema_wire,
)
from dart_crawler.result import JsonObject, Result

_JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


def _page(*, rows: tuple[ExcelRow, ...]) -> ExcelPage:
    return ExcelPage(
        domain=ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        columns=("name", "note"),
        rows=rows,
        total_rows=len(rows),
        offset=0,
        page_size=10,
        returned_rows=len(rows),
    )


def test_result_is_explicitly_duplicated_into_call_tool_result() -> None:
    # Given: a typed Result containing escaped and non-ASCII page data.
    result = Result.success(
        _page(rows=({"name": "한글", "note": 'quote " and newline\n'},))
    )

    # When: the MCP boundary explicitly maps the Result.
    call_result = excel_result_to_call_tool_result(result)

    # Then: text JSON and structuredContent duplicate the same envelope exactly.
    assert len(call_result.content) == 1
    content = call_result.content[0]
    assert isinstance(content, TextContent)
    structured = _JSON_OBJECT_ADAPTER.validate_python(call_result.structured_content)
    assert _JSON_OBJECT_ADAPTER.validate_json(content.text) == structured
    assert structured == _JSON_OBJECT_ADAPTER.validate_python(
        result.model_dump(by_alias=True, mode="json")
    )
    assert call_result.is_error is False


def test_wire_oracle_uses_both_pinned_sdk_profiles_and_full_envelope() -> None:
    # Given: a page Result and the maximum permitted independently encoded ID.
    result = Result.success(_page(rows=({"name": "alpha", "note": "beta"},)))
    assert len(json.dumps(WIRE_REQUEST_ID, separators=(",", ":")).encode()) == 1_024

    # When: both enabled pinned SDK serializer surfaces render full HTTP bodies.
    report = measure_excel_result_wire(result)
    by_profile = {measurement.profile: measurement for measurement in report.measurements}
    legacy = _JSON_OBJECT_ADAPTER.validate_json(
        by_profile[WireProfile.LEGACY].body
    )
    modern = _JSON_OBJECT_ADAPTER.validate_json(
        by_profile[WireProfile.MODERN].body
    )

    # Then: aliases, omission/injection, identity stamp, and byte maxima are exact.
    assert set(by_profile) == {WireProfile.LEGACY, WireProfile.MODERN}
    assert legacy["id"] == WIRE_REQUEST_ID
    assert modern["id"] == WIRE_REQUEST_ID
    legacy_result = legacy["result"]
    modern_result = modern["result"]
    assert isinstance(legacy_result, dict)
    assert isinstance(modern_result, dict)
    assert "structuredContent" in legacy_result
    assert "resultType" not in legacy_result
    assert "_meta" not in legacy_result
    assert modern_result["resultType"] == "complete"
    assert modern_result["_meta"] == {
        "io.modelcontextprotocol/serverInfo": {
            "name": MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION,
        }
    }
    assert report.maximum_bytes == max(
        len(measurement.body) for measurement in report.measurements
    )
    assert all(
        measurement.byte_length == len(measurement.body)
        for measurement in report.measurements
    )


def test_schema_probe_is_internal_and_smaller_than_the_actual_candidate() -> None:
    # Given: a page candidate containing one very wide row.
    result = Result.success(
        _page(rows=({"name": "x" * 10_000, "note": "y" * 10_000},))
    )

    # When: the oracle measures its internal row-free schema probe first.
    schema_report = measure_excel_schema_wire(result)
    candidate_report = measure_excel_result_wire(result)

    # Then: only the report escapes the oracle and the actual row adds wire bytes.
    assert schema_report.maximum_bytes < candidate_report.maximum_bytes
    assert type(schema_report).__name__ == "WireSizeReport"
