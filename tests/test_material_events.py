import re
from dataclasses import dataclass, field

import pytest

from dart_crawler.domains.material_events import MATERIAL_EVENTS, MaterialEventService
from dart_crawler.domains.registry import RegistryEntry, as_registry
from dart_crawler.mcp_server import mcp
from dart_crawler.query_limits import (
    LOCAL_QUERY_LIMITS,
    MAX_RESPONSE_ROWS,
    MAX_RESPONSE_TEXT_CHARS,
    MAX_TOPICS_PER_QUERY,
)
from dart_crawler.result import ErrorCode, JsonObject, Result, WarningCode, error_info

_CORP_CODE = "00126380"
_BGN_DE = "20240101"
_END_DE = "20241231"
_BANKRUPTCY_ENDPOINT = MATERIAL_EVENTS["bankruptcy"].endpoint
_MERGER_ENDPOINT = MATERIAL_EVENTS["merger"].endpoint


@dataclass(slots=True)
class RecordingMaterialEventSource:
    """Hand-rolled MaterialEventSource fake, keyed by endpoint, recording calls."""

    results: dict[str, Result[tuple[JsonObject, ...]]] = field(default_factory=dict)
    calls: list[tuple[str, str, str, str]] = field(default_factory=list)

    def fetch_material_event_rows(
        self,
        endpoint: str,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[tuple[JsonObject, ...]]:
        self.calls.append((endpoint, corp_code, bgn_de, end_de))
        return self.results[endpoint]


def _event_row(**overrides: str) -> JsonObject:
    base: JsonObject = {
        "corp_code": _CORP_CODE,
        "rcept_no": "20240115000123",
        "repror": "홍길동",
    }
    base.update(overrides)
    return base


def _not_found() -> Result[tuple[JsonObject, ...]]:
    return Result[tuple[JsonObject, ...]].failure(
        error_info(
            ErrorCode.NOT_FOUND, "OpenDART 조회 결과가 없습니다.", retryable=False
        )
    )


# --- registry integrity -----------------------------------------------------


def test_registry_keys_and_endpoints_match_naming_rules() -> None:
    key_pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    endpoint_pattern = re.compile(r"^[A-Za-z]+$")
    for event in MATERIAL_EVENTS.values():
        assert key_pattern.match(event.key) is not None
        assert endpoint_pattern.match(event.endpoint) is not None


def test_registry_has_no_duplicate_keys_or_endpoints() -> None:
    keys = [event.key for event in MATERIAL_EVENTS.values()]
    endpoints = [event.endpoint for event in MATERIAL_EVENTS.values()]

    assert len(keys) == len(set(keys))
    assert len(endpoints) == len(set(endpoints))


def test_registry_has_all_36_ds005_event_types() -> None:
    # Guards against an accidental deletion during registry maintenance
    assert len(MATERIAL_EVENTS) == 36


def test_as_registry_rejects_a_duplicate_key() -> None:
    with pytest.raises(ValueError, match="duplicate material event key"):
        as_registry(
            RegistryEntry("dup", "EndpointA", "라벨A"),
            RegistryEntry("dup", "EndpointB", "라벨B"),
            noun="material event",
        )


def test_as_registry_rejects_a_duplicate_endpoint() -> None:
    with pytest.raises(ValueError, match="duplicate material event endpoint"):
        as_registry(
            RegistryEntry("key_a", "SameEndpoint", "라벨A"),
            RegistryEntry("key_b", "SameEndpoint", "라벨B"),
            noun="material event",
        )


@pytest.mark.parametrize("event", list(MATERIAL_EVENTS.values()), ids=lambda e: e.key)
def test_get_routes_each_event_type_to_its_own_endpoint_and_echoes_its_label(
    event: RegistryEntry,
) -> None:
    # Given: one fixture row for this event type's endpoint only
    rows = (_event_row(),)
    source = RecordingMaterialEventSource(
        results={event.endpoint: Result.success(rows)}
    )
    service = MaterialEventService(source)

    # When
    result = service.get(_CORP_CODE, (event.key,), _BGN_DE, _END_DE)

    # Then: the single event type routed to exactly its own endpoint
    assert result.ok is True
    assert result.data is not None
    assert len(result.data.events) == 1
    assert result.data.events[0].event_type == event.key
    assert result.data.events[0].label == event.label
    assert result.data.events[0].rows == rows
    assert source.calls == [(event.endpoint, _CORP_CODE, _BGN_DE, _END_DE)]


# --- docstring drift guard ---------------------------------------------------


@pytest.mark.anyio
async def test_get_material_events_docstring_lists_every_registry_key() -> None:
    # Given the registered local-surface tool
    listed = await mcp.list_tools()
    tool = next(tool for tool in listed if tool.name == "get_material_events")

    # Then: the docstring names every currently registered event_type key, so
    # a registry-only extension without a docstring update fails this test.
    assert tool.description is not None
    for event in MATERIAL_EVENTS.values():
        assert event.key in tool.description


# --- date-range guards (bgn_de/end_de REQUIRED, unlike ownership.py) --------


def test_get_rejects_missing_bgn_de_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), "", _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "bgn_de"
    assert result.next_action is not None
    assert "YYYYMMDD" in result.next_action
    assert source.calls == []


def test_get_rejects_missing_end_de_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), _BGN_DE, "")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "end_de"
    assert source.calls == []


def test_get_rejects_a_malformed_bgn_de_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), "2024-01-01", _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "bgn_de"
    assert result.error.details["value"] == "2024-01-01"
    assert source.calls == []


def test_get_rejects_a_malformed_end_de_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), _BGN_DE, "20241332abc")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "end_de"
    assert source.calls == []


def test_get_rejects_bgn_de_after_end_de_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), "20240201", "20240101")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"bgn_de": "20240201", "end_de": "20240101"}
    assert source.calls == []


# --- corp_code and event_types guards ---------------------------------------


def test_get_rejects_a_malformed_corp_code_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get("not-8-digits", ("bankruptcy",), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert source.calls == []


def test_get_rejects_empty_event_types_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, (), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert source.calls == []


def test_get_rejects_more_than_the_event_type_limit_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)
    event_types = tuple(f"event_{index}" for index in range(MAX_TOPICS_PER_QUERY + 1))

    result = service.get(_CORP_CODE, event_types, _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "event_type_count": MAX_TOPICS_PER_QUERY + 1,
        "limit": MAX_TOPICS_PER_QUERY,
    }
    assert source.calls == []


def test_get_rejects_duplicate_event_types_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy", "bankruptcy"), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"duplicate_event_types": ["bankruptcy"]}
    assert source.calls == []


def test_get_rejects_unknown_event_type_without_calling_source() -> None:
    source = RecordingMaterialEventSource()
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("not_an_event",), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["unknown_event_types"] == ["not_an_event"]
    assert result.error.details["supported_event_types"] == [
        {"event_type": event.key, "label": event.label}
        for event in MATERIAL_EVENTS.values()
    ]
    assert result.next_action is not None
    assert "supported_event_types" in result.next_action
    assert source.calls == []


# --- success paths -------------------------------------------------------------


def test_get_two_event_types_preserves_request_order_and_labels() -> None:
    merger_rows = (_event_row(), _event_row(seq="2"))
    bankruptcy_rows = (_event_row(seq="only"),)
    source = RecordingMaterialEventSource(
        results={
            _MERGER_ENDPOINT: Result.success(merger_rows),
            _BANKRUPTCY_ENDPOINT: Result.success(bankruptcy_rows),
        }
    )
    service = MaterialEventService(source)

    # When: requested in the reverse of registry declaration order
    result = service.get(_CORP_CODE, ("merger", "bankruptcy"), _BGN_DE, _END_DE)

    # Then: request order (not registry order) is preserved
    assert result.ok is True
    assert result.data is not None
    assert [event.event_type for event in result.data.events] == [
        "merger",
        "bankruptcy",
    ]
    assert result.data.events[0].label == MATERIAL_EVENTS["merger"].label
    assert result.data.events[1].label == MATERIAL_EVENTS["bankruptcy"].label
    assert result.data.events[0].rows == merger_rows
    assert result.data.events[1].rows == bankruptcy_rows
    assert result.data.events[0].rows[1]["seq"] == "2"
    assert result.data.returned_row_count == len(merger_rows) + len(bankruptcy_rows)
    assert result.data.bgn_de == _BGN_DE
    assert result.data.end_de == _END_DE
    assert result.warnings == ()
    assert source.calls == [
        (_MERGER_ENDPOINT, _CORP_CODE, _BGN_DE, _END_DE),
        (_BANKRUPTCY_ENDPOINT, _CORP_CODE, _BGN_DE, _END_DE),
    ]


def test_get_one_empty_event_type_succeeds_with_partial_collection_warning() -> None:
    rows = (_event_row(),)
    source = RecordingMaterialEventSource(
        results={
            _MERGER_ENDPOINT: Result.success(rows),
            _BANKRUPTCY_ENDPOINT: _not_found(),
        }
    )
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("merger", "bankruptcy"), _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert result.data.events[1].row_count == 0
    assert result.data.events[1].rows == ()
    assert result.data.returned_row_count == len(rows)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code is WarningCode.PARTIAL_COLLECTION
    assert warning.details["empty_event_types"] == ["bankruptcy"]


def test_get_all_event_types_empty_still_succeeds_with_warning() -> None:
    # Given: this is the policy divergence from report_topics.get, where an
    # all-empty result fails NOT_FOUND — a period with no filed events of the
    # requested types is itself the answer, so this must succeed instead.
    source = RecordingMaterialEventSource(
        results={
            _MERGER_ENDPOINT: _not_found(),
            _BANKRUPTCY_ENDPOINT: Result[tuple[JsonObject, ...]].success(()),
        }
    )
    service = MaterialEventService(source)

    # When
    result = service.get(_CORP_CODE, ("merger", "bankruptcy"), _BGN_DE, _END_DE)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == 0
    assert [event.event_type for event in result.data.events] == [
        "merger",
        "bankruptcy",
    ]
    assert all(event.rows == () for event in result.data.events)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code is WarningCode.PARTIAL_COLLECTION
    assert warning.details["empty_event_types"] == ["merger", "bankruptcy"]


def test_get_stops_after_first_upstream_auth_failure() -> None:
    # Given: only the first event type has a scripted response, so a second
    # call would raise a KeyError and fail the test just as loudly as an assert.
    auth_failure = Result[tuple[JsonObject, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_AUTH,
            "OpenDART API 키가 등록되지 않았습니다.",
            retryable=False,
        )
    )
    source = RecordingMaterialEventSource(results={_MERGER_ENDPOINT: auth_failure})
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("merger", "bankruptcy"), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH
    assert len(source.calls) == 1
    assert source.calls[0][0] == _MERGER_ENDPOINT


def test_extended_registry_serves_a_new_event_type_with_no_other_code_changes() -> None:
    # Given: a registry extended by one entry, mirroring how DS005 coverage
    # would grow if OpenDART ever added a 37th event type
    extra_event = RegistryEntry("new_event", "SomeNewEndpoint", "새로운 사유")
    registry = as_registry(
        *MATERIAL_EVENTS.values(), extra_event, noun="material event"
    )
    rows = (_event_row(),)
    source = RecordingMaterialEventSource(
        results={extra_event.endpoint: Result.success(rows)}
    )
    service = MaterialEventService(source, registry=registry)

    # When
    result = service.get(_CORP_CODE, ("new_event",), _BGN_DE, _END_DE)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.events[0].event_type == "new_event"
    assert result.data.events[0].label == "새로운 사유"
    assert source.calls == [(extra_event.endpoint, _CORP_CODE, _BGN_DE, _END_DE)]


# --- size guards -------------------------------------------------------------


def test_get_rejects_row_count_over_limit_and_drops_rows() -> None:
    rows = tuple(_event_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS + 1))
    source = RecordingMaterialEventSource(
        results={_BANKRUPTCY_ENDPOINT: Result.success(rows)}
    )
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }
    assert result.next_action == "기간을 좁히거나 event_type을 나누어 호출하세요."


def test_get_rejects_text_over_the_char_budget_and_drops_rows() -> None:
    # Given: two rows whose narrative text alone exceeds the budget, while
    # staying far under the row-count limit (isolates the text-budget guard)
    big_text = "가" * (MAX_RESPONSE_TEXT_CHARS // 2 + 1)
    rows = (_event_row(repror=big_text), _event_row(repror=big_text))
    source = RecordingMaterialEventSource(
        results={_BANKRUPTCY_ENDPOINT: Result.success(rows)}
    )
    service = MaterialEventService(source)

    result = service.get(_CORP_CODE, ("bankruptcy",), _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    returned_text_char_count = result.error.details["returned_text_char_count"]
    assert isinstance(returned_text_char_count, int)
    assert returned_text_char_count > MAX_RESPONSE_TEXT_CHARS
    assert result.error.details["text_char_limit"] == MAX_RESPONSE_TEXT_CHARS
    assert result.next_action == "기간을 좁히거나 event_type을 나누어 호출하세요."


def test_get_accepts_over_remote_response_limits_with_local_limits() -> None:
    # Given
    rows = (
        *(_event_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS)),
        _event_row(repror="가" * (MAX_RESPONSE_TEXT_CHARS + 1)),
    )
    source = RecordingMaterialEventSource(
        results={_BANKRUPTCY_ENDPOINT: Result.success(rows)}
    )
    service = MaterialEventService(source, limits=LOCAL_QUERY_LIMITS)

    # When
    result = service.get(_CORP_CODE, ("bankruptcy",), _BGN_DE, _END_DE)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == MAX_RESPONSE_ROWS + 1
