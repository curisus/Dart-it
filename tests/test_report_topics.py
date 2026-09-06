import re
from dataclasses import dataclass, field

import pytest

from dart_crawler.dart_api import DartApi
from dart_crawler.domains.report_topics import (
    REPORT_TOPICS,
    ReportTopic,
    ReportTopicService,
    _as_registry,
)
from dart_crawler.http_client import HttpResponse
from dart_crawler.mcp_server import mcp
from dart_crawler.query_limits import (
    LOCAL_QUERY_LIMITS,
    MAX_RESPONSE_ROWS,
    MAX_RESPONSE_TEXT_CHARS,
    MAX_TOPICS_PER_QUERY,
)
from dart_crawler.result import ErrorCode, JsonObject, Result, WarningCode, error_info

_CORP_CODE = "00126380"
_BSNS_YEAR = 2023
_REPRT_CODE = "11011"
_AUDIT_OPINION_ENDPOINT = REPORT_TOPICS["audit_opinion"].endpoint
_AUDIT_SERVICE_ENDPOINT = REPORT_TOPICS["audit_service_contract"].endpoint


@dataclass(slots=True)
class RecordingReportTopicSource:
    """Hand-rolled ReportTopicSource fake, keyed by endpoint, recording calls."""

    results: dict[str, Result[tuple[JsonObject, ...]]] = field(default_factory=dict)
    calls: list[tuple[str, str, int, str]] = field(default_factory=list)

    def fetch_report_topic_rows(
        self,
        endpoint: str,
        corp_code: str,
        business_year: int,
        report_code: str,
    ) -> Result[tuple[JsonObject, ...]]:
        self.calls.append((endpoint, corp_code, business_year, report_code))
        return self.results[endpoint]


def _topic_row(**overrides: str) -> JsonObject:
    base: JsonObject = {
        "corp_code": _CORP_CODE,
        "bsns_year": str(_BSNS_YEAR),
        "adtor": "삼일회계법인",
    }
    base.update(overrides)
    return base


def _not_found() -> Result[tuple[JsonObject, ...]]:
    return Result[tuple[JsonObject, ...]].failure(
        error_info(ErrorCode.NOT_FOUND, "OpenDART 조회 결과가 없습니다.", retryable=False)
    )


# --- registry integrity -----------------------------------------------------


def test_registry_keys_and_endpoints_match_naming_rules() -> None:
    # Given / When: the shipped registry
    # Then: every key is snake_case and every endpoint is a bare path segment
    key_pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    endpoint_pattern = re.compile(r"^[A-Za-z]+$")
    for topic in REPORT_TOPICS.values():
        assert key_pattern.match(topic.key) is not None
        assert endpoint_pattern.match(topic.endpoint) is not None


def test_registry_has_no_duplicate_keys_or_endpoints() -> None:
    keys = [topic.key for topic in REPORT_TOPICS.values()]
    endpoints = [topic.endpoint for topic in REPORT_TOPICS.values()]

    assert len(keys) == len(set(keys))
    assert len(endpoints) == len(set(endpoints))


def test_as_registry_rejects_a_duplicate_key() -> None:
    # Given two topics sharing a key
    # When / Then
    with pytest.raises(ValueError, match="duplicate report topic key"):
        _as_registry(
            ReportTopic("dup", "EndpointA", "라벨A"),
            ReportTopic("dup", "EndpointB", "라벨B"),
        )


def test_as_registry_rejects_a_duplicate_endpoint() -> None:
    # Given two topics sharing an endpoint
    # When / Then
    with pytest.raises(ValueError, match="duplicate report topic endpoint"):
        _as_registry(
            ReportTopic("key_a", "SameEndpoint", "라벨A"),
            ReportTopic("key_b", "SameEndpoint", "라벨B"),
        )


def test_registry_has_all_28_ds002_topics() -> None:
    # Guards against an accidental deletion during registry maintenance
    assert len(REPORT_TOPICS) == 28


@pytest.mark.parametrize("topic", list(REPORT_TOPICS.values()), ids=lambda t: t.key)
def test_get_routes_each_topic_to_its_own_endpoint_and_echoes_its_label(
    topic: ReportTopic,
) -> None:
    # Given: one fixture row for this topic's endpoint only
    rows = (_topic_row(),)
    source = RecordingReportTopicSource(results={topic.endpoint: Result.success(rows)})
    service = ReportTopicService(source)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, (topic.key,))

    # Then: the single topic routed to exactly this topic's endpoint
    assert result.ok is True
    assert result.data is not None
    assert len(result.data.topics) == 1
    assert result.data.topics[0].topic == topic.key
    assert result.data.topics[0].label == topic.label
    assert result.data.topics[0].rows == rows
    assert source.calls == [(topic.endpoint, _CORP_CODE, _BSNS_YEAR, _REPRT_CODE)]


# --- docstring drift guard ---------------------------------------------------


@pytest.mark.anyio
async def test_get_report_topics_docstring_lists_every_registry_topic() -> None:
    # Given the registered local-surface tool
    listed = await mcp.list_tools()
    tool = next(tool for tool in listed if tool.name == "get_report_topics")

    # Then: the docstring names every currently registered topic key, so a
    # registry-only extension without a docstring update fails this test.
    assert tool.description is not None
    for topic in REPORT_TOPICS.values():
        assert topic.key in tool.description


# --- input guards -------------------------------------------------------------


def test_get_rejects_unknown_topic_without_calling_source() -> None:
    # Given
    source = RecordingReportTopicSource()
    service = ReportTopicService(source)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("not_a_topic",))

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["unknown_topics"] == ["not_a_topic"]
    assert result.error.details["supported_topics"] == [
        {"topic": topic.key, "label": topic.label} for topic in REPORT_TOPICS.values()
    ]
    assert result.next_action is not None
    for topic in REPORT_TOPICS:
        assert topic in result.next_action
    assert source.calls == []


def test_get_rejects_empty_topics_without_calling_source() -> None:
    # Given
    source = RecordingReportTopicSource()
    service = ReportTopicService(source)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ())

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert source.calls == []


def test_get_rejects_more_than_the_topic_limit_without_calling_source() -> None:
    # Given
    source = RecordingReportTopicSource()
    service = ReportTopicService(source)
    topics = tuple(f"topic_{index}" for index in range(MAX_TOPICS_PER_QUERY + 1))

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, topics)

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "topic_count": MAX_TOPICS_PER_QUERY + 1,
        "limit": MAX_TOPICS_PER_QUERY,
    }
    assert source.calls == []


def test_local_profile_still_rejects_eleven_topics_without_calling_source() -> None:
    assert not hasattr(LOCAL_QUERY_LIMITS, "max_topics_per_query")
    source = RecordingReportTopicSource()
    service = ReportTopicService(source, limits=LOCAL_QUERY_LIMITS)
    topics = tuple(f"topic_{index}" for index in range(MAX_TOPICS_PER_QUERY + 1))

    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, topics)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "topic_count": MAX_TOPICS_PER_QUERY + 1,
        "limit": MAX_TOPICS_PER_QUERY,
    }
    assert source.calls == []


def test_get_rejects_duplicate_topics_without_calling_source() -> None:
    # Given
    source = RecordingReportTopicSource()
    service = ReportTopicService(source)

    # When
    result = service.get(
        _CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("audit_opinion", "audit_opinion")
    )

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"duplicate_topics": ["audit_opinion"]}
    assert source.calls == []


# --- success paths -------------------------------------------------------------


def test_get_two_topics_preserves_request_order_and_labels() -> None:
    # Given
    audit_service_rows = (
        _topic_row(contract_fee="1000000"),
        _topic_row(contract_fee="2000000", totally_unknown_field="kept"),
    )
    audit_opinion_rows = (_topic_row(adt_opinion="적정"),)
    source = RecordingReportTopicSource(
        results={
            _AUDIT_SERVICE_ENDPOINT: Result.success(audit_service_rows),
            _AUDIT_OPINION_ENDPOINT: Result.success(audit_opinion_rows),
        }
    )
    service = ReportTopicService(source)

    # When: requested in the reverse of registry declaration order
    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_service_contract", "audit_opinion"),
    )

    # Then: request order (not registry order) is preserved
    assert result.ok is True
    assert result.data is not None
    assert [topic.topic for topic in result.data.topics] == [
        "audit_service_contract",
        "audit_opinion",
    ]
    assert result.data.topics[0].label == REPORT_TOPICS["audit_service_contract"].label
    assert result.data.topics[1].label == REPORT_TOPICS["audit_opinion"].label
    assert result.data.topics[0].rows == audit_service_rows
    assert result.data.topics[1].rows == audit_opinion_rows
    assert result.data.topics[0].rows[1]["totally_unknown_field"] == "kept"
    assert result.data.returned_row_count == len(audit_service_rows) + len(
        audit_opinion_rows
    )
    assert result.warnings == ()
    assert source.calls == [
        (_AUDIT_SERVICE_ENDPOINT, _CORP_CODE, _BSNS_YEAR, _REPRT_CODE),
        (_AUDIT_OPINION_ENDPOINT, _CORP_CODE, _BSNS_YEAR, _REPRT_CODE),
    ]


def test_get_one_empty_topic_succeeds_with_partial_collection_warning() -> None:
    # Given
    rows = (_topic_row(),)
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: Result.success(rows),
            _AUDIT_SERVICE_ENDPOINT: _not_found(),
        }
    )
    service = ReportTopicService(source)

    # When
    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract"),
    )

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.topics[1].row_count == 0
    assert result.data.topics[1].rows == ()
    assert result.data.returned_row_count == len(rows)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code is WarningCode.PARTIAL_COLLECTION
    assert warning.details["empty_topics"] == ["audit_service_contract"]


def test_get_all_topics_empty_fails_with_not_found() -> None:
    # Given
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: _not_found(),
            _AUDIT_SERVICE_ENDPOINT: _not_found(),
        }
    )
    service = ReportTopicService(source)

    # When
    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract"),
    )

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.details["empty_topics"] == [
        "audit_opinion",
        "audit_service_contract",
    ]
    assert result.next_action is not None


def test_get_stops_after_first_non_not_found_failure() -> None:
    # Given: only the first topic has a scripted response, so a second call
    # would raise a KeyError and fail the test just as loudly as an assert.
    auth_failure = Result[tuple[JsonObject, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_AUTH,
            "OpenDART API 키가 등록되지 않았습니다.",
            retryable=False,
        )
    )
    source = RecordingReportTopicSource(results={_AUDIT_OPINION_ENDPOINT: auth_failure})
    service = ReportTopicService(source)

    # When
    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract"),
    )

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH
    assert len(source.calls) == 1
    assert source.calls[0][0] == _AUDIT_OPINION_ENDPOINT


def test_extended_registry_serves_a_new_topic_with_no_other_code_changes() -> None:
    # Given: a registry extended by one entry, as Phase 2 (24 more topics)
    # will do repeatedly
    extra_topic = ReportTopic(
        "outside_director", "SomeNewEndpoint", "사외이사 및 그 변동현황"
    )
    registry = _as_registry(*REPORT_TOPICS.values(), extra_topic)
    rows = (_topic_row(),)
    source = RecordingReportTopicSource(results={extra_topic.endpoint: Result.success(rows)})
    service = ReportTopicService(source, registry=registry)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("outside_director",))

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.topics[0].topic == "outside_director"
    assert result.data.topics[0].label == "사외이사 및 그 변동현황"
    assert source.calls == [(extra_topic.endpoint, _CORP_CODE, _BSNS_YEAR, _REPRT_CODE)]


# --- size guards -------------------------------------------------------------


def test_get_rejects_row_count_over_limit_and_drops_rows() -> None:
    # Given
    rows = tuple(_topic_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS + 1))
    source = RecordingReportTopicSource(
        results={_AUDIT_OPINION_ENDPOINT: Result.success(rows)}
    )
    service = ReportTopicService(source)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("audit_opinion",))

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }
    assert result.next_action == "topic을 나누어 호출하세요."


def test_get_rejects_text_over_the_char_budget_and_drops_rows() -> None:
    # Given: two rows whose narrative text alone exceeds the budget, while
    # staying far under the row-count limit (isolates the text-budget guard)
    big_text = "가" * (MAX_RESPONSE_TEXT_CHARS // 2 + 1)
    rows = (_topic_row(adt_opinion=big_text), _topic_row(adt_opinion=big_text))
    source = RecordingReportTopicSource(
        results={_AUDIT_OPINION_ENDPOINT: Result.success(rows)}
    )
    service = ReportTopicService(source)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("audit_opinion",))

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    returned_text_char_count = result.error.details["returned_text_char_count"]
    assert isinstance(returned_text_char_count, int)
    assert returned_text_char_count > MAX_RESPONSE_TEXT_CHARS
    assert result.error.details["text_char_limit"] == MAX_RESPONSE_TEXT_CHARS
    assert result.next_action == "topic을 나누어 호출하세요."


def test_get_accepts_over_remote_response_limits_with_local_limits() -> None:
    # Given
    rows = (
        *(_topic_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS)),
        _topic_row(adt_opinion="가" * (MAX_RESPONSE_TEXT_CHARS + 1)),
    )
    source = RecordingReportTopicSource(
        results={_AUDIT_OPINION_ENDPOINT: Result.success(rows)}
    )
    service = ReportTopicService(source, limits=LOCAL_QUERY_LIMITS)

    # When
    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("audit_opinion",))

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == MAX_RESPONSE_ROWS + 1


# --- transport (DartApi.fetch_report_topic_rows) ------------------------------


@dataclass
class FakeHttpClient:
    responses: list[HttpResponse]
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.requests.append((url, params))
        return self.responses.pop(0)

    def close(self) -> None:
        return None


def test_fetch_report_topic_rows_builds_endpoint_url_and_preserves_unknown_fields() -> (
    None
):
    # Given
    body = (
        '{"status":"000","message":"OK","list":[{"corp_code":"00126380",'
        '"adtor":"삼일회계법인",'
        '"totally_unknown_field":"kept"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    # When
    result = api.fetch_report_topic_rows(
        "accnutAdtorNmNdAdtOpinion", _CORP_CODE, _BSNS_YEAR, _REPRT_CODE
    )

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data[0]["adtor"] == "삼일회계법인"
    assert result.data[0]["totally_unknown_field"] == "kept"
    assert client.requests[0][0].endswith("accnutAdtorNmNdAdtOpinion.json")
    assert client.requests[0][1]["corp_code"] == _CORP_CODE
    assert client.requests[0][1]["bsns_year"] == str(_BSNS_YEAR)
    assert client.requests[0][1]["reprt_code"] == _REPRT_CODE


def test_fetch_report_topic_rows_maps_not_found_status() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"013","message":"no data"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_report_topic_rows(
        "adtServcCnclsSttus", _CORP_CODE, _BSNS_YEAR, _REPRT_CODE
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_fetch_report_topic_rows_maps_auth_failure_status() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"010","message":"bad key"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_report_topic_rows(
        "adtServcCnclsSttus", _CORP_CODE, _BSNS_YEAR, _REPRT_CODE
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH


def test_fetch_report_topic_rows_rejects_malformed_endpoint_without_http_call() -> None:
    # Given: an empty response list means any HTTP call would raise IndexError
    client = FakeHttpClient([])
    api = DartApi(client, api_key="test-key")

    # When
    result = api.fetch_report_topic_rows(
        "bad endpoint!", _CORP_CODE, _BSNS_YEAR, _REPRT_CODE
    )

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert client.requests == []


def test_get_all_topics_empty_via_status_000_fails_not_found() -> None:
    # Given: every topic answers DART status "000" with an empty list,
    # which the transport surfaces as Result.success(()) — not a 013 failure
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: Result[tuple[JsonObject, ...]].success(()),
            _AUDIT_SERVICE_ENDPOINT: Result[tuple[JsonObject, ...]].success(()),
        }
    )
    service = ReportTopicService(source)

    # When
    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract"),
    )

    # Then: the all-empty contract still fails with NOT_FOUND
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.details["empty_topics"] == [
        "audit_opinion",
        "audit_service_contract",
    ]


def test_get_mixed_empty_success_and_not_found_warns_about_both() -> None:
    # Given: one topic has rows, one is empty via status 000, one via 013
    non_audit_endpoint = REPORT_TOPICS["non_audit_service_contract"].endpoint
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: Result[tuple[JsonObject, ...]].success(
                (_topic_row(),)
            ),
            _AUDIT_SERVICE_ENDPOINT: Result[tuple[JsonObject, ...]].success(()),
            non_audit_endpoint: _not_found(),
        }
    )
    service = ReportTopicService(source)

    # When
    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract", "non_audit_service_contract"),
    )

    # Then: success, and the warning names BOTH kinds of empty topics
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == 1
    assert [warning.code for warning in result.warnings] == [
        WarningCode.PARTIAL_COLLECTION
    ]
    assert result.warnings[0].details["empty_topics"] == [
        "audit_service_contract",
        "non_audit_service_contract",
    ]


# --- U-04: placeholder rows count as an empty topic --------------------------


def _placeholder_row() -> JsonObject:
    """OpenDART answers "해당 없음" with one row whose values are all "-"."""
    return {
        "corp_code": _CORP_CODE,
        "corp_name": "삼성전자",
        "rcept_no": "20260310002820",
        "stlm_dt": "2025-12-31",
        "se": "-",
        "cnt": "-",
        "amount": "-",
    }


def test_a_placeholder_only_topic_is_reported_as_empty() -> None:
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: Result.success((_placeholder_row(),)),
        }
    )
    service = ReportTopicService(source)

    result = service.get(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, ("audit_opinion",))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.details["empty_topics"] == ["audit_opinion"]


def test_a_placeholder_only_topic_beside_a_real_one_warns() -> None:
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: Result.success((_topic_row(),)),
            _AUDIT_SERVICE_ENDPOINT: Result.success((_placeholder_row(),)),
        }
    )
    service = ReportTopicService(source)

    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract"),
    )

    assert result.ok is True
    assert result.data is not None
    assert [warning.code for warning in result.warnings] == [
        WarningCode.PARTIAL_COLLECTION
    ]
    assert result.warnings[0].details["empty_topics"] == ["audit_service_contract"]
    counts = {
        item.topic: (item.row_count, item.substantive_row_count)
        for item in result.data.topics
    }
    assert counts == {
        "audit_opinion": (1, 1),
        "audit_service_contract": (1, 0),
    }


def test_the_source_row_is_still_returned_verbatim() -> None:
    """The placeholder row is data OpenDART sent; only the count judges it."""
    placeholder = _placeholder_row()
    source = RecordingReportTopicSource(
        results={
            _AUDIT_OPINION_ENDPOINT: Result.success((_topic_row(),)),
            _AUDIT_SERVICE_ENDPOINT: Result.success((placeholder,)),
        }
    )
    service = ReportTopicService(source)

    result = service.get(
        _CORP_CODE,
        _BSNS_YEAR,
        _REPRT_CODE,
        ("audit_opinion", "audit_service_contract"),
    )

    assert result.data is not None
    assert result.data.topics[1].rows == (placeholder,)
    assert result.data.returned_row_count == 2
