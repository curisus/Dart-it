import pytest

from dart_crawler.api_models import DartGroup
from dart_crawler.domains.registration_statements import (
    REGISTRATION_STATEMENTS,
    RegistrationStatementService,
)
from dart_crawler.query_limits import (
    LOCAL_QUERY_LIMITS,
    MAX_RESPONSE_ROWS,
    MAX_RESPONSE_TEXT_CHARS,
)
from dart_crawler.result import ErrorCode, JsonObject, Result, error_info

_CORP_CODE = "00126380"
_BGN_DE = "20240101"
_END_DE = "20241231"
_EQUITY_ENDPOINT = REGISTRATION_STATEMENTS["equity_securities"].endpoint


class RecordingRegistrationStatementSource:
    """Endpoint-keyed DS006 source fake that records each source call."""

    __slots__ = ("calls", "results")

    def __init__(
        self,
        results: dict[str, Result[tuple[DartGroup[JsonObject], ...]]] | None = None,
    ) -> None:
        """Create a source fake with optional scripted endpoint results."""
        self.results = {} if results is None else results
        self.calls: list[tuple[str, str, str, str]] = []

    def fetch_registration_statement_groups(
        self,
        endpoint: str,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[tuple[DartGroup[JsonObject], ...]]:
        """Return a scripted DS006 result for one endpoint."""
        self.calls.append((endpoint, corp_code, bgn_de, end_de))
        return self.results[endpoint]


def _statement_row(**overrides: str) -> JsonObject:
    """Build one row-shaped JSON object while preserving caller overrides."""
    base: JsonObject = {
        "corp_code": _CORP_CODE,
        "rcept_no": "20240115000123",
        "corp_name": "Sample",
    }
    base.update(overrides)
    return base


def _source_failure(error_code: ErrorCode) -> Result[tuple[DartGroup[JsonObject], ...]]:
    """Build one non-empty upstream failure result for propagation tests."""
    return Result[tuple[DartGroup[JsonObject], ...]].failure(
        error_info(error_code, f"{error_code.value} from source", retryable=True)
    )


def test_get_rejects_malformed_corp_code_without_calling_source() -> None:
    """Given a malformed corp_code, then validation fails before source I/O."""
    source = RecordingRegistrationStatementSource()
    service = RegistrationStatementService(source)

    result = service.get("not-8-digits", "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"corp_code": "not-8-digits"}
    assert source.calls == []


def test_get_rejects_missing_bgn_de_without_calling_source() -> None:
    """Given a missing start date, then validation fails before a source call."""
    source = RecordingRegistrationStatementSource()
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", "", _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "bgn_de"
    assert result.next_action is not None
    assert "YYYYMMDD" in result.next_action
    assert source.calls == []


def test_get_rejects_missing_end_de_without_calling_source() -> None:
    """Given a missing end date, then validation fails before a source call."""
    source = RecordingRegistrationStatementSource()
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, "")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["field"] == "end_de"
    assert result.next_action is not None
    assert "YYYYMMDD" in result.next_action
    assert source.calls == []


def test_get_rejects_malformed_date_without_calling_source() -> None:
    """Given a malformed date, then validation fails before a source call."""
    source = RecordingRegistrationStatementSource()
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", "2024-01-01", _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"field": "bgn_de", "value": "2024-01-01"}
    assert source.calls == []


def test_get_rejects_inverted_date_range_without_calling_source() -> None:
    """Given bgn_de after end_de, then validation fails before source I/O."""
    source = RecordingRegistrationStatementSource()
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", "20240201", "20240101")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"bgn_de": "20240201", "end_de": "20240101"}
    assert source.calls == []


def test_get_rejects_unknown_stmt_type_without_calling_source() -> None:
    """Given an unsupported stmt_type, then details name it and all supported values."""
    source = RecordingRegistrationStatementSource()
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "unknown", _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["stmt_type"] == "unknown"
    assert result.error.details["supported_stmt_types"] == [
        {"stmt_type": statement.key, "label": statement.label}
        for statement in REGISTRATION_STATEMENTS.values()
    ]
    assert source.calls == []


@pytest.mark.parametrize(
    "error_code",
    [
        ErrorCode.UPSTREAM_AUTH,
        ErrorCode.PARSE_FAILED,
        ErrorCode.UPSTREAM_UNAVAILABLE,
    ],
)
def test_get_propagates_upstream_failure_without_data(error_code: ErrorCode) -> None:
    """Given a non-013 source failure, then DS006 returns that failure without data."""
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: _source_failure(error_code)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is error_code
    assert source.calls == [(_EQUITY_ENDPOINT, _CORP_CODE, _BGN_DE, _END_DE)]


def test_get_rejects_row_count_over_limit_and_drops_groups() -> None:
    """Given too many rows, then DS006 fails instead of returning truncated groups."""
    rows = tuple(
        _statement_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS + 1)
    )
    groups = (DartGroup[JsonObject](title="일반사항", list=rows),)
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: Result.success(groups)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }
    assert result.next_action == "기간을 좁혀 다시 호출하세요."


def test_get_rejects_text_over_char_budget_and_drops_groups() -> None:
    """Given too much row text, then DS006 fails without returning partial groups."""
    big_text = "가" * (MAX_RESPONSE_TEXT_CHARS // 2 + 1)
    groups = (
        DartGroup[JsonObject](
            title="일반사항",
            list=(_statement_row(note=big_text), _statement_row(note=big_text)),
        ),
    )
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: Result.success(groups)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    returned_text_char_count = result.error.details["returned_text_char_count"]
    assert isinstance(returned_text_char_count, int)
    assert returned_text_char_count > MAX_RESPONSE_TEXT_CHARS
    assert result.error.details["text_char_limit"] == MAX_RESPONSE_TEXT_CHARS
    assert result.next_action == "기간을 좁혀 다시 호출하세요."


def test_get_accepts_over_remote_response_limits_with_local_limits() -> None:
    # Given
    rows = (
        *(_statement_row(seq=str(index)) for index in range(MAX_RESPONSE_ROWS)),
        _statement_row(note="가" * (MAX_RESPONSE_TEXT_CHARS + 1)),
    )
    groups = (DartGroup[JsonObject](title="일반사항", list=rows),)
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: Result.success(groups)}
    )
    service = RegistrationStatementService(source, limits=LOCAL_QUERY_LIMITS)

    # When
    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == MAX_RESPONSE_ROWS + 1
