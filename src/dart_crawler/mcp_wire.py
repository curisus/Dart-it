from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, TypeVar

from mcp_types import (
    SERVER_INFO_META_KEY,
    CallToolResult,
    JSONRPCResponse,
    TextContent,
)
from mcp_types.methods import serialize_server_result
from pydantic import TypeAdapter

from dart_crawler.excel_page_models import (
    ExcelDataDomain,
    ExcelPage,
    ExcelProvenance,
    ExcelRow,
)
from dart_crawler.result import JsonObject, Result, WarningInfo

MCP_SERVER_NAME: Final = "dart_crawler"
MCP_SERVER_VERSION: Final = "0.1.0"
WIRE_REQUEST_ID: Final = "i" * 1_022
_JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)
_TOOLS_CALL_METHOD: Final = "tools/call"

__all__ = [
    "MCP_SERVER_NAME",
    "MCP_SERVER_VERSION",
    "WIRE_REQUEST_ID",
    "WireProfile",
    "WireProfileMeasurement",
    "WireSizeReport",
    "excel_result_to_call_tool_result",
    "measure_excel_result_wire",
    "measure_excel_schema_wire",
]

ModelT = TypeVar("ModelT")


@unique
class WireProfile(StrEnum):
    LEGACY = "2025-11-25"
    MODERN = "2026-07-28"


@dataclass(frozen=True, slots=True)
class WireProfileMeasurement:
    profile: WireProfile
    body: bytes

    @property
    def byte_length(self) -> int:
        return len(self.body)


@dataclass(frozen=True, slots=True)
class WireSizeReport:
    measurements: tuple[WireProfileMeasurement, ...]

    @property
    def maximum_bytes(self) -> int:
        return max(item.byte_length for item in self.measurements)

    def fits_strictly(self, budget_bytes: int) -> bool:
        return all(item.byte_length < budget_bytes for item in self.measurements)


@dataclass(frozen=True, slots=True)
class _SchemaWireProbe:
    schema_version: int
    domain: ExcelDataDomain
    request_fingerprint: str
    source_fingerprint: str
    dataset_id: str
    columns: tuple[str, ...]
    rows: tuple[ExcelRow, ...]
    warnings: tuple[WarningInfo, ...]
    provenance: ExcelProvenance
    total_rows: int
    offset: int
    page_index: int
    page_size: int
    returned_rows: int
    next_cursor: str | None


def excel_result_to_call_tool_result(result: Result[ModelT]) -> CallToolResult:
    structured = _JSON_OBJECT_ADAPTER.validate_python(
        result.model_dump(by_alias=True, mode="json")
    )
    text = json.dumps(
        structured,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return CallToolResult(
        content=[TextContent(text=text)],
        structured_content=structured,
        is_error=not result.ok,
    )


def measure_excel_result_wire(result: Result[ExcelPage]) -> WireSizeReport:
    return _measure_model_result(result)


def measure_excel_schema_wire(result: Result[ExcelPage]) -> WireSizeReport:
    page = result.data
    if page is None:
        msg = "schema wire measurement requires a successful page Result"
        raise ValueError(msg)
    probe = _SchemaWireProbe(
        schema_version=page.schema_version,
        domain=page.domain,
        request_fingerprint=page.request_fingerprint,
        source_fingerprint=page.source_fingerprint,
        dataset_id=page.dataset_id,
        columns=page.columns,
        rows=(),
        warnings=page.warnings,
        provenance=page.provenance,
        total_rows=page.total_rows,
        offset=page.offset,
        page_index=page.page_index,
        page_size=page.page_size,
        returned_rows=0,
        next_cursor=None,
    )
    probe_result = Result[_SchemaWireProbe].success(probe)
    return _measure_model_result(probe_result)


def _measure_model_result(result: Result[ModelT]) -> WireSizeReport:
    call_result = excel_result_to_call_tool_result(result)
    measurements = tuple(
        WireProfileMeasurement(
            profile=profile,
            body=_render_profile(call_result, profile),
        )
        for profile in WireProfile
    )
    return WireSizeReport(measurements=measurements)


def _render_profile(
    call_result: CallToolResult,
    profile: WireProfile,
) -> bytes:
    dumped = call_result.model_dump(
        by_alias=True,
        mode="json",
        exclude_none=True,
    )
    wire_result = serialize_server_result(
        _TOOLS_CALL_METHOD,
        profile.value,
        dumped,
    )
    if profile is WireProfile.MODERN:
        wire_result["_meta"] = {
            SERVER_INFO_META_KEY: {
                "name": MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION,
            }
        }
    response = JSONRPCResponse(
        jsonrpc="2.0",
        id=WIRE_REQUEST_ID,
        result=wire_result,
    )
    if profile is WireProfile.LEGACY:
        return response.model_dump_json(
            by_alias=True,
            exclude_unset=True,
        ).encode("utf-8")
    response_value = response.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    return json.dumps(response_value, separators=(",", ":")).encode("utf-8")
