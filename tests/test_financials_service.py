from dataclasses import dataclass, field

from dart_crawler.api_models import FinancialAccount, FinancialIndexRow, MajorAccountRow
from dart_crawler.dart_api import FinancialQuery
from dart_crawler.domains.financials import FinancialsService
from dart_crawler.domains.query_guards import MAX_COMPANIES_PER_QUERY, MAX_RESPONSE_ROWS
from dart_crawler.result import ErrorCode, Result, WarningCode, WarningInfo, error_info

_CORP_CODE = "00126380"
_OTHER_CORP_CODE = "00164742"
_BSNS_YEAR = 2023
_REPRT_CODE = "11011"
_IDX_CL_CODE = "M210000"


@dataclass(slots=True)
class RecordingFinancialSource:
    """Hand-rolled FinancialSource fake that records calls and returns scripts."""

    financial_accounts_result: Result[tuple[FinancialAccount, ...]] | None = None
    major_accounts_result: Result[tuple[MajorAccountRow, ...]] | None = None
    financial_indexes_result: Result[tuple[FinancialIndexRow, ...]] | None = None

    financial_accounts_calls: list[FinancialQuery] = field(default_factory=list)
    major_accounts_calls: list[tuple[tuple[str, ...], int, str]] = field(
        default_factory=list
    )
    financial_indexes_calls: list[tuple[tuple[str, ...], int, str, str]] = field(
        default_factory=list
    )

    def fetch_financial_accounts(
        self,
        query: FinancialQuery,
    ) -> Result[tuple[FinancialAccount, ...]]:
        self.financial_accounts_calls.append(query)
        assert self.financial_accounts_result is not None
        return self.financial_accounts_result

    def fetch_major_accounts(
        self,
        corp_codes: tuple[str, ...],
        business_year: int,
        report_code: str,
    ) -> Result[tuple[MajorAccountRow, ...]]:
        self.major_accounts_calls.append((corp_codes, business_year, report_code))
        assert self.major_accounts_result is not None
        return self.major_accounts_result

    def fetch_financial_indexes(
        self,
        corp_codes: tuple[str, ...],
        business_year: int,
        report_code: str,
        index_class: str,
    ) -> Result[tuple[FinancialIndexRow, ...]]:
        self.financial_indexes_calls.append(
            (corp_codes, business_year, report_code, index_class)
        )
        assert self.financial_indexes_result is not None
        return self.financial_indexes_result


def _financial_account(**overrides: str) -> FinancialAccount:
    base: dict[str, str] = {
        "fs_div": "OFS",
        "sj_div": "BS",
        "bsns_year": "2023",
        "reprt_code": "11011",
        "account_id": "ifrs-full_Assets",
        "account_nm": "자산총계",
    }
    base.update(overrides)
    return FinancialAccount(**base)


def _major_account_row(**overrides: str) -> MajorAccountRow:
    base: dict[str, str] = {
        "reprt_code": "11011",
        "bsns_year": "2023",
        "fs_div": "OFS",
        "sj_div": "BS",
        "account_nm": "자산총계",
    }
    base.update(overrides)
    return MajorAccountRow(**base)


def _financial_index_row(**overrides: str) -> FinancialIndexRow:
    base: dict[str, str] = {"bsns_year": "2023"}
    base.update(overrides)
    return FinancialIndexRow(**base)


def test_full_statements_success_echoes_query_and_row_count() -> None:
    # Given
    accounts = (_financial_account(), _financial_account(account_nm="부채총계"))
    source = RecordingFinancialSource(
        financial_accounts_result=Result.success(accounts)
    )
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.corp_code == _CORP_CODE
    assert result.data.bsns_year == _BSNS_YEAR
    assert result.data.reprt_code == _REPRT_CODE
    assert result.data.fs_div == "OFS"
    assert result.data.returned_row_count == len(accounts)
    assert result.data.accounts == accounts
    assert source.financial_accounts_calls == [
        FinancialQuery(
            corp_code=_CORP_CODE,
            business_year=_BSNS_YEAR,
            report_code=_REPRT_CODE,
            statement_scope="OFS",
        )
    ]


def test_full_statements_rejects_invalid_reprt_code_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, "99999", "OFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["supported_reprt_codes"] == [
        "11011",
        "11012",
        "11013",
        "11014",
    ]
    assert result.next_action is not None
    assert source.financial_accounts_calls == []


def test_full_statements_rejects_bsns_year_before_2015_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, 2014, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["minimum_bsns_year"] == 2015
    assert source.financial_accounts_calls == []


def test_full_statements_rejects_invalid_fs_div_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "XFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["supported_fs_divs"] == ["CFS", "OFS"]
    assert source.financial_accounts_calls == []


def test_full_statements_rejects_seven_digit_corp_code_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.full_statements("1234567", _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"corp_code": "1234567"}
    assert result.next_action is not None
    assert "search_companies" in result.next_action
    assert source.financial_accounts_calls == []


def test_full_statements_rejects_non_digit_corp_code_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.full_statements("abcdefgh", _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"corp_code": "abcdefgh"}
    assert source.financial_accounts_calls == []


def test_full_statements_cfs_not_found_carries_ofs_hint() -> None:
    # Given
    not_found = Result[tuple[FinancialAccount, ...]].failure(
        error_info(ErrorCode.NOT_FOUND, "OpenDART 조회 결과가 없습니다.", retryable=False)
    )
    source = RecordingFinancialSource(financial_accounts_result=not_found)
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "CFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.next_action is not None
    assert "OFS" in result.next_action


def test_full_statements_ofs_not_found_has_no_cfs_hint() -> None:
    # Given
    not_found = Result[tuple[FinancialAccount, ...]].failure(
        error_info(ErrorCode.NOT_FOUND, "OpenDART 조회 결과가 없습니다.", retryable=False)
    )
    source = RecordingFinancialSource(financial_accounts_result=not_found)
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.next_action is None


def test_full_statements_propagates_upstream_failure_unchanged() -> None:
    # Given
    warning = WarningInfo(
        code=WarningCode.PARTIAL_COLLECTION,
        message="일부 계정만 수집되었습니다.",
    )
    upstream_failure = Result[tuple[FinancialAccount, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "OpenDART 전체 계정과목을 수집할 수 없습니다.",
            retryable=True,
        ),
        warnings=(warning,),
        next_action="잠시 후 다시 시도하세요.",
    )
    source = RecordingFinancialSource(financial_accounts_result=upstream_failure)
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is False
    assert result.error == upstream_failure.error
    assert result.warnings == (warning,)
    assert result.next_action == "잠시 후 다시 시도하세요."


def test_full_statements_rejects_row_count_over_limit_and_drops_rows() -> None:
    # Given
    accounts = tuple(
        _financial_account(account_id=f"acc-{index}")
        for index in range(MAX_RESPONSE_ROWS + 1)
    )
    source = RecordingFinancialSource(
        financial_accounts_result=Result.success(accounts)
    )
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }


def test_major_accounts_rejects_empty_corp_codes_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.major_accounts((), _BSNS_YEAR, _REPRT_CODE)

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert source.major_accounts_calls == []


def test_major_accounts_rejects_too_many_corp_codes_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)
    corp_codes = tuple(f"{index:08d}" for index in range(MAX_COMPANIES_PER_QUERY + 1))

    # When
    result = service.major_accounts(corp_codes, _BSNS_YEAR, _REPRT_CODE)

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "corp_code_count": MAX_COMPANIES_PER_QUERY + 1,
        "limit": MAX_COMPANIES_PER_QUERY,
    }
    assert source.major_accounts_calls == []


def test_major_accounts_rejects_malformed_corp_code_element_without_calling_source() -> (
    None
):
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.major_accounts(
        (_CORP_CODE, "bad-code"), _BSNS_YEAR, _REPRT_CODE
    )

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {"invalid_corp_codes": ["bad-code"]}
    assert source.major_accounts_calls == []


def test_major_accounts_rejects_row_count_over_limit_and_drops_rows() -> None:
    # Given
    rows = tuple(
        _major_account_row(account_nm=f"계정-{index}")
        for index in range(MAX_RESPONSE_ROWS + 1)
    )
    source = RecordingFinancialSource(major_accounts_result=Result.success(rows))
    service = FinancialsService(source)

    # When
    result = service.major_accounts((_CORP_CODE,), _BSNS_YEAR, _REPRT_CODE)

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details == {
        "returned_row_count": MAX_RESPONSE_ROWS + 1,
        "limit": MAX_RESPONSE_ROWS,
    }
    assert result.next_action is not None
    assert "회사" in result.next_action


def test_major_accounts_propagates_upstream_failure_unchanged() -> None:
    # Given
    upstream_failure = Result[tuple[MajorAccountRow, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "OpenDART 주요계정 재무정보를 수집할 수 없습니다.",
            retryable=True,
        )
    )
    source = RecordingFinancialSource(major_accounts_result=upstream_failure)
    service = FinancialsService(source)

    # When
    result = service.major_accounts((_CORP_CODE,), _BSNS_YEAR, _REPRT_CODE)

    # Then
    assert result.ok is False
    assert result.error == upstream_failure.error


def test_major_accounts_success_forwards_exact_args_in_order() -> None:
    # Given
    rows = (_major_account_row(),)
    source = RecordingFinancialSource(major_accounts_result=Result.success(rows))
    service = FinancialsService(source)
    corp_codes = (_OTHER_CORP_CODE, _CORP_CODE)

    # When
    result = service.major_accounts(corp_codes, _BSNS_YEAR, _REPRT_CODE)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.corp_codes == corp_codes
    assert result.data.returned_row_count == len(rows)
    assert result.data.accounts == rows
    assert source.major_accounts_calls == [(corp_codes, _BSNS_YEAR, _REPRT_CODE)]


def test_indicators_rejects_invalid_idx_cl_code_without_calling_source() -> None:
    # Given
    source = RecordingFinancialSource()
    service = FinancialsService(source)

    # When
    result = service.indicators((_CORP_CODE,), _BSNS_YEAR, _REPRT_CODE, "M999999")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.details["supported_idx_cl_codes"] == [
        "M210000",
        "M220000",
        "M230000",
        "M240000",
    ]
    assert source.financial_indexes_calls == []


def test_indicators_success_forwards_exact_args() -> None:
    # Given
    rows = (_financial_index_row(idx_cl_code=_IDX_CL_CODE),)
    source = RecordingFinancialSource(financial_indexes_result=Result.success(rows))
    service = FinancialsService(source)
    corp_codes = (_CORP_CODE, _OTHER_CORP_CODE)

    # When
    result = service.indicators(corp_codes, _BSNS_YEAR, _REPRT_CODE, _IDX_CL_CODE)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.corp_codes == corp_codes
    assert result.data.idx_cl_code == _IDX_CL_CODE
    assert result.data.returned_row_count == len(rows)
    assert result.data.indicators == rows
    assert source.financial_indexes_calls == [
        (corp_codes, _BSNS_YEAR, _REPRT_CODE, _IDX_CL_CODE)
    ]


def test_major_accounts_accepts_exactly_the_company_limit() -> None:
    # Given
    rows = (_major_account_row(),)
    source = RecordingFinancialSource(major_accounts_result=Result.success(rows))
    service = FinancialsService(source)
    corp_codes = tuple(f"{index:08d}" for index in range(MAX_COMPANIES_PER_QUERY))

    # When
    result = service.major_accounts(corp_codes, _BSNS_YEAR, _REPRT_CODE)

    # Then
    assert result.ok is True
    assert source.major_accounts_calls == [(corp_codes, _BSNS_YEAR, _REPRT_CODE)]


def test_full_statements_accepts_exactly_the_row_limit() -> None:
    # Given
    accounts = tuple(
        _financial_account(account_nm=f"계정{index}")
        for index in range(MAX_RESPONSE_ROWS)
    )
    source = RecordingFinancialSource(
        financial_accounts_result=Result.success(accounts)
    )
    service = FinancialsService(source)

    # When
    result = service.full_statements(_CORP_CODE, _BSNS_YEAR, _REPRT_CODE, "OFS")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == MAX_RESPONSE_ROWS
