import pytest
from pydantic import ValidationError

from dart_crawler.excel_company_arguments import (
    ListReportAttachmentsArguments,
    ListReportFilingsArguments,
    SearchCompaniesArguments,
)
from dart_crawler.excel_disclosure_arguments import (
    GetMaterialEventsArguments,
    GetOwnershipReportsArguments,
    GetRegistrationStatementsArguments,
    GetReportTopicsArguments,
)
from dart_crawler.excel_financial_arguments import (
    GetFinancialIndicatorsArguments,
    GetFinancialStatementsArguments,
    GetMajorAccountsArguments,
)
from dart_crawler.excel_report_arguments import GetReportSectionsArguments


def _major_arguments(corp_codes: list[str]) -> dict[str, str | int | list[str]]:
    return {
        "corp_codes": corp_codes,
        "bsns_year": 2025,
        "reprt_code": "11011",
    }


def _indicator_arguments(
    corp_codes: list[str],
) -> dict[str, str | int | list[str]]:
    return {
        **_major_arguments(corp_codes),
        "idx_cl_code": "M210000",
    }


def test_selection_fields_accept_only_json_arrays() -> None:
    with pytest.raises(ValidationError):
        GetMajorAccountsArguments.model_validate(
            {
                "corp_codes": ("00123456",),
                "bsns_year": 2025,
                "reprt_code": "11011",
            }
        )
    with pytest.raises(ValidationError):
        GetReportTopicsArguments.model_validate(
            {
                "corp_code": "00123456",
                "bsns_year": 2025,
                "reprt_code": "11011",
                "topics": "dividend",
            }
        )
    with pytest.raises(ValidationError):
        GetMaterialEventsArguments.model_validate(
            {
                "corp_code": "00123456",
                "event_types": {"merger"},
                "bgn_de": "20250101",
                "end_de": "20251231",
            }
        )
    with pytest.raises(ValidationError):
        GetReportSectionsArguments.model_validate(
            {
                "rcept_no": "20260101000001",
                "attachment_id": "id",
                "section_ids": 7,
            }
        )


def test_strict_year_rejects_bool_and_numeric_string() -> None:
    with pytest.raises(ValidationError):
        GetFinancialStatementsArguments.model_validate(
            {
                "corp_code": "00123456",
                "bsns_year": True,
                "reprt_code": "11011",
            }
        )
    with pytest.raises(ValidationError):
        GetFinancialStatementsArguments.model_validate(
            {
                "corp_code": "00123456",
                "bsns_year": "2025",
                "reprt_code": "11011",
            }
        )


def test_unknown_fields_and_unregistered_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchCompaniesArguments.model_validate(
            {"company_query": "회사", "unexpected": "value"}
        )
    with pytest.raises(ValidationError):
        SearchCompaniesArguments.model_validate(
            {"company_query": "회사", "report_kind": "unknown"}
        )
    with pytest.raises(ValidationError):
        ListReportFilingsArguments.model_validate(
            {"corp_code": "00123456", "report_kind": "unknown"}
        )
    with pytest.raises(ValidationError):
        GetRegistrationStatementsArguments.model_validate(
            {
                "corp_code": "00123456",
                "stmt_type": "unknown",
                "bgn_de": "20250101",
                "end_de": "20251231",
            }
        )


def test_identifiers_require_exact_ascii_digits() -> None:
    with pytest.raises(ValidationError):
        GetFinancialStatementsArguments.model_validate(
            {
                "corp_code": "\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18",
                "bsns_year": 2025,
                "reprt_code": "11011",
            }
        )
    with pytest.raises(ValidationError):
        ListReportAttachmentsArguments.model_validate(
            {"rcept_no": "2026010100000"}
        )
    with pytest.raises(ValidationError):
        ListReportAttachmentsArguments.model_validate(
            {
                "rcept_no": (
                    "\uff12\uff10\uff12\uff16\uff10\uff11\uff10"
                    "\uff11\uff10\uff10\uff10\uff10\uff10\uff11"
                )
            }
        )


def test_selections_require_unique_registered_values() -> None:
    with pytest.raises(ValidationError):
        GetMajorAccountsArguments.model_validate(
            _major_arguments(["00123456", "00123456"])
        )
    with pytest.raises(ValidationError):
        GetReportTopicsArguments.model_validate(
            {
                "corp_code": "00123456",
                "bsns_year": 2025,
                "reprt_code": "11011",
                "topics": ["dividend", "dividend"],
            }
        )
    with pytest.raises(ValidationError):
        GetMaterialEventsArguments.model_validate(
            {
                "corp_code": "00123456",
                "event_types": ["not_registered"],
                "bgn_de": "20250101",
                "end_de": "20251231",
            }
        )


def test_report_sections_require_one_unique_registered_selector() -> None:
    common = {
        "rcept_no": "20260101000001",
        "attachment_id": "id",
    }
    with pytest.raises(ValidationError):
        GetReportSectionsArguments.model_validate(common)
    with pytest.raises(ValidationError):
        GetReportSectionsArguments.model_validate(
            {**common, "section_ids": ["s001-other", "s001-other"]}
        )
    with pytest.raises(ValidationError):
        GetReportSectionsArguments.model_validate(
            {**common, "section_kinds": ["not_registered"]}
        )


def test_dates_are_lexical_and_preserve_optional_period_semantics() -> None:
    lexical = GetRegistrationStatementsArguments.model_validate(
        {
            "corp_code": "00123456",
            "stmt_type": "equity_securities",
            "bgn_de": "20251340",
            "end_de": "20251399",
        }
    )
    open_period = GetOwnershipReportsArguments.model_validate(
        {
            "corp_code": "00123456",
            "report_type": "major_holding",
            "bgn_de": "",
            "end_de": "20251231",
        }
    )

    assert lexical.bgn_de == "20251340"
    assert open_period.bgn_de == ""
    with pytest.raises(ValidationError):
        GetOwnershipReportsArguments.model_validate(
            {
                "corp_code": "00123456",
                "report_type": "major_holding",
                "bgn_de": "20251231",
                "end_de": "20250101",
            }
        )
    with pytest.raises(ValidationError):
        GetRegistrationStatementsArguments.model_validate(
            {
                "corp_code": "00123456",
                "stmt_type": "equity_securities",
                "bgn_de": "",
                "end_de": "20251231",
            }
        )


def test_company_batch_limit_is_exactly_one_hundred() -> None:
    one_hundred = [f"{index:08d}" for index in range(100)]

    major = GetMajorAccountsArguments.model_validate(
        _major_arguments(one_hundred)
    )
    indicators = GetFinancialIndicatorsArguments.model_validate(
        _indicator_arguments(one_hundred)
    )

    assert major.corp_codes == tuple(one_hundred)
    assert indicators.corp_codes == tuple(one_hundred)
    with pytest.raises(ValidationError):
        GetMajorAccountsArguments.model_validate(
            _major_arguments([*one_hundred, "00000100"])
        )
    with pytest.raises(ValidationError):
        GetFinancialIndicatorsArguments.model_validate(
            _indicator_arguments([*one_hundred, "00000100"])
        )
