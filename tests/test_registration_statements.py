import pytest

from dart_crawler.api_models import DartGroup
from dart_crawler.domains.registration_statements import (
    REGISTRATION_STATEMENTS,
    RegistrationStatementData,
    RegistrationStatementGroup,
    RegistrationStatementService,
)
from dart_crawler.domains.registry import RegistryEntry, as_registry
from dart_crawler.result import ErrorCode, JsonObject, Result, WarningCode, error_info

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


def _not_found() -> Result[tuple[DartGroup[JsonObject], ...]]:
    """Build the adapter result shape for OpenDART status 013."""
    return Result[tuple[DartGroup[JsonObject], ...]].failure(
        error_info(
            ErrorCode.NOT_FOUND,
            "OpenDART 조회 결과가 없습니다.",
            retryable=False,
        )
    )


def test_registry_has_the_six_ds006_stmt_types() -> None:
    """Given the DS006 registry, then it exposes exactly the six plan keys."""
    assert [
        (statement.key, statement.endpoint, statement.label)
        for statement in REGISTRATION_STATEMENTS.values()
    ] == [
        ("equity_securities", "estkRs", "증권신고서(지분증권)"),
        ("debt_securities", "bdRs", "증권신고서(채무증권)"),
        ("depositary_receipts", "stkdpRs", "증권신고서(증권예탁증권)"),
        ("merger", "mgRs", "증권신고서(합병)"),
        (
            "stock_exchange_transfer",
            "extrRs",
            "증권신고서(주식의포괄적교환·이전)",
        ),
        ("division", "dvRs", "증권신고서(분할)"),
    ]


@pytest.mark.parametrize("statement", list(REGISTRATION_STATEMENTS.values()))
def test_get_routes_each_stmt_type_to_its_endpoint_and_official_label(
    statement: RegistryEntry,
) -> None:
    """Given any registered stmt_type, then it routes to its own endpoint."""
    groups = (DartGroup[JsonObject](title="group", list=(_statement_row(),)),)
    source = RecordingRegistrationStatementSource(
        {statement.endpoint: Result.success(groups)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, statement.key, _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert result.data.stmt_type == statement.key
    assert result.data.label == statement.label
    assert result.data.groups[0].title == "group"
    assert source.calls == [(statement.endpoint, _CORP_CODE, _BGN_DE, _END_DE)]


def test_models_expose_exact_contract_fields() -> None:
    """Given the DS006 models, then they expose only the plan-contract fields."""
    assert tuple(RegistrationStatementGroup.model_fields) == (
        "title",
        "row_count",
        "rows",
    )
    assert tuple(RegistrationStatementData.model_fields) == (
        "corp_code",
        "stmt_type",
        "label",
        "bgn_de",
        "end_de",
        "returned_group_count",
        "returned_row_count",
        "groups",
    )


def test_get_preserves_group_order_titles_and_unknown_row_fields() -> None:
    """Given grouped DS006 rows, when fetched, then source group shape is preserved."""
    groups = (
        DartGroup[JsonObject](title="일반사항", list=(_statement_row(sbd="20240120"),)),
        DartGroup[JsonObject](
            title="증권의종류",
            list=(_statement_row(totally_unknown_field="kept"),),
        ),
    )
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: Result.success(groups)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert result.data.stmt_type == "equity_securities"
    assert result.data.label == "증권신고서(지분증권)"
    assert result.data.returned_group_count == 2
    assert [group.title for group in result.data.groups] == ["일반사항", "증권의종류"]
    assert result.data.groups[1].rows[0]["totally_unknown_field"] == "kept"
    assert result.data.returned_row_count == 2
    assert result.warnings == ()
    assert source.calls == [(_EQUITY_ENDPOINT, _CORP_CODE, _BGN_DE, _END_DE)]


def test_get_nonempty_overall_result_with_empty_group_has_no_warning() -> None:
    """Given at least one DS006 row, then empty sibling groups do not warn."""
    groups = (
        DartGroup[JsonObject](title="일반사항", list=(_statement_row(),)),
        DartGroup[JsonObject](title="빈그룹", list=()),
    )
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: Result.success(groups)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert [group.row_count for group in result.data.groups] == [1, 0]
    assert result.data.returned_group_count == 2
    assert result.data.returned_row_count == 1
    assert result.warnings == ()


def test_get_all_000_empty_groups_succeeds_with_partial_collection_warning() -> None:
    """Given only empty status-000 groups, then the call succeeds with a warning."""
    groups = (
        DartGroup[JsonObject](title="일반사항", list=()),
        DartGroup[JsonObject](title="증권의종류", list=()),
    )
    source = RecordingRegistrationStatementSource(
        {_EQUITY_ENDPOINT: Result.success(groups)}
    )
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_group_count == 2
    assert result.data.returned_row_count == 0
    assert [group.title for group in result.data.groups] == ["일반사항", "증권의종류"]
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code is WarningCode.PARTIAL_COLLECTION
    assert warning.details == {"empty_stmt_type": "equity_securities"}


def test_get_status_013_succeeds_empty_with_partial_collection_warning() -> None:
    """Given OpenDART status 013, then DS006 returns an empty successful payload."""
    source = RecordingRegistrationStatementSource({_EQUITY_ENDPOINT: _not_found()})
    service = RegistrationStatementService(source)

    result = service.get(_CORP_CODE, "equity_securities", _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert result.data.groups == ()
    assert result.data.returned_group_count == 0
    assert result.data.returned_row_count == 0
    assert result.warnings[0].code is WarningCode.PARTIAL_COLLECTION
    assert result.warnings[0].details == {"empty_stmt_type": "equity_securities"}


def test_extended_registry_serves_a_new_stmt_type() -> None:
    """Given an extended registry, then one new stmt_type works without code changes."""
    extra_statement = RegistryEntry("new_statement", "newRs", "새 증권신고서")
    registry = as_registry(
        *REGISTRATION_STATEMENTS.values(),
        extra_statement,
        noun="registration statement",
    )
    groups = (DartGroup[JsonObject](title="새 그룹", list=(_statement_row(),)),)
    source = RecordingRegistrationStatementSource(
        {extra_statement.endpoint: Result.success(groups)}
    )
    service = RegistrationStatementService(source, registry=registry)

    result = service.get(_CORP_CODE, "new_statement", _BGN_DE, _END_DE)

    assert result.ok is True
    assert result.data is not None
    assert result.data.stmt_type == "new_statement"
    assert result.data.label == "새 증권신고서"
