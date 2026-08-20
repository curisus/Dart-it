from dataclasses import dataclass, field

import pytest

from dart_crawler.domains.ownership import (
    OWNERSHIP_REPORTS,
    OwnershipReport,
    OwnershipService,
    _as_report_registry,
)
from dart_crawler.domains.query_guards import MAX_RESPONSE_ROWS
from dart_crawler.result import ErrorCode, JsonObject, Result, WarningCode, error_info
from dart_crawler.section_models import MAX_RESPONSE_TEXT_CHARS

_CORP_CODE = "00126380"
_MAJOR_HOLDING_ENDPOINT = OWNERSHIP_REPORTS["major_holding"].endpoint
_INSIDER_ENDPOINT = OWNERSHIP_REPORTS["insider_ownership"].endpoint


@dataclass(slots=True)
class RecordingOwnershipSource:
    """Hand-rolled OwnershipSource fake, keyed by endpoint, recording calls."""

    results: dict[str, Result[tuple[JsonObject, ...]]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def fetch_ownership_rows(
        self,
        endpoint: str,
        corp_code: str,
    ) -> Result[tuple[JsonObject, ...]]:
        self.calls.append((endpoint, corp_code))
        return self.results[endpoint]


def _row(**overrides: str) -> JsonObject:
    base: JsonObject = {
        "corp_code": _CORP_CODE,
        "report_tp": "신규",
        "repror": "홍길동",
    }
    base.update(overrides)
    return base


def _dated_row(rcept_dt: str, **overrides: str) -> JsonObject:
    return _row(rcept_dt=rcept_dt, **overrides)


def _not_found() -> Result[tuple[JsonObject, ...]]:
    return Result[tuple[JsonObject, ...]].failure(
        error_info(ErrorCode.NOT_FOUND, "OpenDART 조회 결과가 없습니다.", retryable=False)
    )


# --- registry integrity -----------------------------------------------------------


def test_registry_has_no_duplicate_keys_or_endpoints() -> None:
    keys = [report.key for report in OWNERSHIP_REPORTS.values()]
    endpoints = [report.endpoint for report in OWNERSHIP_REPORTS.values()]

    assert len(keys) == len(set(keys))
    assert len(endpoints) == len(set(endpoints))


def test_registry_has_the_two_ds004_report_types() -> None:
    assert set(OWNERSHIP_REPORTS) == {"major_holding", "insider_ownership"}


def test_as_report_registry_rejects_a_duplicate_key() -> None:
    with pytest.raises(ValueError, match="duplicate ownership report key"):
        _as_report_registry(
            OwnershipReport("dup", "EndpointA", "라벨A"),
            OwnershipReport("dup", "EndpointB", "라벨B"),
        )


def test_as_report_registry_rejects_a_duplicate_endpoint() -> None:
    with pytest.raises(ValueError, match="duplicate ownership report endpoint"):
        _as_report_registry(
            OwnershipReport("key_a", "SameEndpoint", "라벨A"),
            OwnershipReport("key_b", "SameEndpoint", "라벨B"),
        )


# --- input guards -------------------------------------------------------------------


def test_get_rejects_a_malformed_corp_code_without_calling_source() -> None:
    source = RecordingOwnershipSource()
    service = OwnershipService(source)

    result = service.get("not-8-digits", "major_holding")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert source.calls == []


def test_get_rejects_an_unknown_report_type_without_calling_source() -> None:
    source = RecordingOwnershipSource()
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "not_a_report_type")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["report_type"] == "not_a_report_type"
    assert result.error.details["supported_report_types"] == [
        {"report_type": report.key, "label": report.label}
        for report in OWNERSHIP_REPORTS.values()
    ]
    assert result.next_action is not None
    for report_type in OWNERSHIP_REPORTS:
        assert report_type in result.next_action
    assert source.calls == []


def test_get_rejects_a_malformed_bgn_de_without_calling_source() -> None:
    source = RecordingOwnershipSource()
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding", bgn_de="2024-01-01")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "bgn_de"
    assert result.error.details["value"] == "2024-01-01"
    assert result.next_action is not None
    assert "YYYYMMDD" in result.next_action
    assert source.calls == []


def test_get_rejects_a_malformed_end_de_without_calling_source() -> None:
    source = RecordingOwnershipSource()
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding", end_de="20240132abc")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "end_de"
    assert source.calls == []


def test_get_rejects_bgn_de_after_end_de_without_calling_source() -> None:
    source = RecordingOwnershipSource()
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240201", end_de="20240101"
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"bgn_de": "20240201", "end_de": "20240101"}
    assert source.calls == []


# --- success paths ----------------------------------------------------------------


def test_get_echoes_report_type_label_and_verbatim_rows() -> None:
    rows = (_row(), _row(report_tp="변동", totally_unknown_field="kept"))
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding")

    assert result.ok is True
    assert result.data is not None
    assert result.data.corp_code == _CORP_CODE
    assert result.data.report_type == "major_holding"
    assert result.data.label == OWNERSHIP_REPORTS["major_holding"].label
    assert result.data.bgn_de == ""
    assert result.data.end_de == ""
    assert result.data.total_row_count == 2
    assert result.data.returned_row_count == 2
    assert result.data.rows == rows
    assert result.data.rows[1]["totally_unknown_field"] == "kept"
    assert result.warnings == ()
    assert source.calls == [(_MAJOR_HOLDING_ENDPOINT, _CORP_CODE)]


def test_get_echoes_bgn_de_end_de_and_total_row_count() -> None:
    rows = (_dated_row("20240115"),)
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240101", end_de="20240131"
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.bgn_de == "20240101"
    assert result.data.end_de == "20240131"
    assert result.data.total_row_count == 1
    assert result.data.returned_row_count == 1


# --- receipt-date range filter ------------------------------------------------------


def test_get_filters_rows_to_the_inclusive_receipt_date_range() -> None:
    rows = (
        _dated_row("20240109", seq="before"),
        _dated_row("20240110", seq="lower_boundary"),
        _dated_row("20240115", seq="inside"),
        _dated_row("20240120", seq="upper_boundary"),
        _dated_row("20240121", seq="after"),
    )
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240110", end_de="20240120"
    )

    assert result.ok is True
    assert result.data is not None
    assert [row["seq"] for row in result.data.rows] == [
        "lower_boundary",
        "inside",
        "upper_boundary",
    ]
    assert result.data.total_row_count == 5
    assert result.data.returned_row_count == 3


def test_get_tolerates_dashes_in_rcept_dt() -> None:
    rows = (_row(rcept_dt="2024-01-15"),)
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240101", end_de="20240131"
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == 1


def test_get_falls_back_to_rcept_no_prefix_when_rcept_dt_is_missing() -> None:
    rows = (
        _row(rcept_no="20240115000123", seq="in_range"),
        _row(rcept_no="20230101000456", seq="out_of_range"),
    )
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240101", end_de="20240131"
    )

    assert result.ok is True
    assert result.data is not None
    assert [row["seq"] for row in result.data.rows] == ["in_range"]


def test_get_keeps_a_row_whose_receipt_date_cannot_be_determined() -> None:
    rows = (_row(),)  # neither rcept_dt nor rcept_no present
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240101", end_de="20240131"
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == 1


def test_get_succeeds_when_the_date_filter_narrows_an_over_limit_result() -> None:
    # This is the regression test for the design gap the range filter fixes:
    # a company whose full history exceeds the row budget can now be split
    # by receipt date instead of being unconditionally rejected.
    out_of_range = tuple(
        _dated_row("20200101", seq=f"old-{index}")
        for index in range(MAX_RESPONSE_ROWS // 2 + 1)
    )
    in_range = tuple(
        _dated_row("20240101", seq=f"new-{index}")
        for index in range(MAX_RESPONSE_ROWS // 2)
    )
    rows = out_of_range + in_range
    assert len(rows) == MAX_RESPONSE_ROWS + 1
    source = RecordingOwnershipSource(results={_INSIDER_ENDPOINT: Result.success(rows)})
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "insider_ownership", bgn_de="20240101", end_de="20240101"
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.total_row_count == MAX_RESPONSE_ROWS + 1
    assert result.data.returned_row_count == len(in_range)
    assert result.data.returned_row_count <= MAX_RESPONSE_ROWS


def test_get_empty_after_filter_succeeds_without_partial_collection_warning() -> None:
    rows = (_dated_row("20200101"), _dated_row("20200215"))
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240101", end_de="20241231"
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.returned_row_count == 0
    assert result.data.total_row_count == 2
    assert result.warnings == ()


def test_get_routes_insider_ownership_to_its_own_endpoint() -> None:
    rows = (_row(),)
    source = RecordingOwnershipSource(results={_INSIDER_ENDPOINT: Result.success(rows)})
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "insider_ownership")

    assert result.ok is True
    assert result.data is not None
    assert result.data.report_type == "insider_ownership"
    assert result.data.label == OWNERSHIP_REPORTS["insider_ownership"].label
    assert source.calls == [(_INSIDER_ENDPOINT, _CORP_CODE)]


# --- empty-result contract (both DART "no data" shapes) ---------------------------


def test_get_empty_success_rows_succeeds_with_partial_collection_warning() -> None:
    # Given: DART status 000 with an empty list
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result[tuple[JsonObject, ...]].success(())}
    )
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding")

    assert result.ok is True
    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.returned_row_count == 0
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code is WarningCode.PARTIAL_COLLECTION
    assert warning.details["report_type"] == "major_holding"


def test_get_not_found_failure_succeeds_with_partial_collection_warning() -> None:
    # Given: DART status 013 (surfaced as a NOT_FOUND failure by the transport)
    source = RecordingOwnershipSource(results={_MAJOR_HOLDING_ENDPOINT: _not_found()})
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding")

    assert result.ok is True
    assert result.data is not None
    assert result.data.rows == ()
    assert result.data.returned_row_count == 0
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code is WarningCode.PARTIAL_COLLECTION
    assert warning.details["report_type"] == "major_holding"


# --- other upstream failure propagation -------------------------------------------


def test_get_propagates_a_non_not_found_failure_unchanged() -> None:
    auth_failure = Result[tuple[JsonObject, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_AUTH,
            "OpenDART API 키가 등록되지 않았습니다.",
            retryable=False,
        )
    )
    source = RecordingOwnershipSource(results={_MAJOR_HOLDING_ENDPOINT: auth_failure})
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH


# --- size guards -------------------------------------------------------------------


def test_get_rejects_row_count_over_limit() -> None:
    rows = tuple(_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS + 1))
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }
    assert result.next_action is not None
    assert "bgn_de" in result.next_action
    assert "end_de" in result.next_action


def test_get_rejects_text_over_the_char_budget() -> None:
    big_text = "가" * (MAX_RESPONSE_TEXT_CHARS // 2 + 1)
    rows = (_row(repror=big_text), _row(repror=big_text))
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(_CORP_CODE, "major_holding")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    returned_text_char_count = result.error.details["returned_text_char_count"]
    assert isinstance(returned_text_char_count, int)
    assert returned_text_char_count > MAX_RESPONSE_TEXT_CHARS
    assert result.error.details["text_char_limit"] == MAX_RESPONSE_TEXT_CHARS
    assert result.next_action is not None
    assert "bgn_de" in result.next_action
    assert "end_de" in result.next_action


def test_get_rejects_over_limit_filtered_rows_and_next_action_mentions_date_range() -> (
    None
):
    rows = tuple(
        _dated_row("20240101", seq=str(index))
        for index in range(MAX_RESPONSE_ROWS + 1)
    )
    source = RecordingOwnershipSource(
        results={_MAJOR_HOLDING_ENDPOINT: Result.success(rows)}
    )
    service = OwnershipService(source)

    result = service.get(
        _CORP_CODE, "major_holding", bgn_de="20240101", end_de="20240101"
    )

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }
    assert result.next_action is not None
    assert "bgn_de" in result.next_action
    assert "end_de" in result.next_action


def test_get_keeps_a_row_whose_rcept_dt_is_malformed() -> None:
    # Given: a filtered query where one row carries junk in rcept_dt and no
    # usable rcept_no (regression: lexicographic comparison against the
    # YYYYMMDD bounds silently dropped such rows instead of keeping them)
    rows: tuple[JsonObject, ...] = (
        {"rcept_dt": "20260701", "repror": "정상 행"},
        {"rcept_dt": "N/A", "repror": "판별 불가 행"},
    )
    source = RecordingOwnershipSource(
        results={"elestock": Result[tuple[JsonObject, ...]].success(rows)}
    )
    service = OwnershipService(source)

    # When
    result = service.get(
        _CORP_CODE, "insider_ownership", bgn_de="20260101", end_de="20261231"
    )

    # Then: the undateable row is kept alongside the in-range row
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == 2
    assert {row["repror"] for row in result.data.rows} == {"정상 행", "판별 불가 행"}
