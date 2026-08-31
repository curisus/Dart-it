from dataclasses import dataclass

import pytest

from dart_crawler.domains.material_events import MATERIAL_EVENTS
from dart_crawler.domains.report_topics import REPORT_TOPICS
from dart_crawler.excel_argument_validation import validate_excel_query
from dart_crawler.excel_disclosure_arguments import (
    GetMaterialEventsArguments,
    GetReportTopicsArguments,
)
from dart_crawler.excel_json_models import model_json_object
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.result import JsonObject


@dataclass(frozen=True, slots=True)
class ArgumentCase:
    domain: ExcelDataDomain
    raw: JsonObject
    expected: JsonObject


EXCEL_ARGUMENT_CASES = (
    ArgumentCase(
        ExcelDataDomain.SEARCH_COMPANIES,
        {"company_query": "회사"},
        {"company_query": "회사", "report_kind": None},
    ),
    ArgumentCase(
        ExcelDataDomain.LIST_REPORT_FILINGS,
        {"corp_code": "00123456", "report_kind": "audit"},
        {"corp_code": "00123456", "report_kind": "audit"},
    ),
    ArgumentCase(
        ExcelDataDomain.LIST_REPORT_ATTACHMENTS,
        {"rcept_no": "20260101000001"},
        {"rcept_no": "20260101000001"},
    ),
    ArgumentCase(
        ExcelDataDomain.LIST_REPORT_SECTIONS,
        {"rcept_no": "20260101000001", "attachment_id": "id"},
        {"rcept_no": "20260101000001", "attachment_id": "id"},
    ),
    ArgumentCase(
        ExcelDataDomain.GET_REPORT_SECTIONS,
        {
            "rcept_no": "20260101000001",
            "attachment_id": "id",
            "section_kinds": ["other"],
        },
        {
            "rcept_no": "20260101000001",
            "attachment_id": "id",
            "section_ids": [],
            "section_kinds": ["other"],
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
        {"corp_code": "00123456", "bsns_year": 2025, "reprt_code": "11011"},
        {
            "corp_code": "00123456",
            "bsns_year": 2025,
            "reprt_code": "11011",
            "fs_div": "CFS",
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        {
            "corp_codes": ["00123456"],
            "bsns_year": 2025,
            "reprt_code": "11011",
        },
        {
            "corp_codes": ["00123456"],
            "bsns_year": 2025,
            "reprt_code": "11011",
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_FINANCIAL_INDICATORS,
        {
            "corp_codes": ["00123456"],
            "bsns_year": 2025,
            "reprt_code": "11011",
            "idx_cl_code": "M210000",
        },
        {
            "corp_codes": ["00123456"],
            "bsns_year": 2025,
            "reprt_code": "11011",
            "idx_cl_code": "M210000",
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_REPORT_TOPICS,
        {
            "corp_code": "00123456",
            "bsns_year": 2025,
            "reprt_code": "11011",
            "topics": ["dividend"],
        },
        {
            "corp_code": "00123456",
            "bsns_year": 2025,
            "reprt_code": "11011",
            "topics": ["dividend"],
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_COMPANY_PROFILE,
        {"corp_code": "00123456"},
        {"corp_code": "00123456"},
    ),
    ArgumentCase(
        ExcelDataDomain.GET_OWNERSHIP_REPORTS,
        {"corp_code": "00123456", "report_type": "major_holding"},
        {
            "corp_code": "00123456",
            "report_type": "major_holding",
            "bgn_de": "",
            "end_de": "",
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_MATERIAL_EVENTS,
        {
            "corp_code": "00123456",
            "event_types": ["merger"],
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
        {
            "corp_code": "00123456",
            "event_types": ["merger"],
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
    ),
    ArgumentCase(
        ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
        {
            "corp_code": "00123456",
            "stmt_type": "equity_securities",
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
        {
            "corp_code": "00123456",
            "stmt_type": "equity_securities",
            "bgn_de": "20250101",
            "end_de": "20251231",
        },
    ),
)


@pytest.mark.parametrize(
    "case",
    EXCEL_ARGUMENT_CASES,
    ids=tuple(case.domain.value for case in EXCEL_ARGUMENT_CASES),
)
def test_every_domain_dumps_exact_default_complete_arguments(case: ArgumentCase) -> None:
    result = validate_excel_query(case.domain, case.raw)

    assert result.data is not None
    assert model_json_object(result.data.arguments) == case.expected


def test_argument_matrix_is_exhaustive() -> None:
    assert {case.domain for case in EXCEL_ARGUMENT_CASES} == set(ExcelDataDomain)


def test_all_registered_topics_validate_together_in_registry_order() -> None:
    topics = tuple(REPORT_TOPICS)

    arguments = GetReportTopicsArguments.model_validate(
        {
            "corp_code": "00123456",
            "bsns_year": 2025,
            "reprt_code": "11011",
            "topics": list(topics),
        }
    )

    assert len(topics) == 28
    assert arguments.topics == topics


def test_all_registered_events_validate_together_in_registry_order() -> None:
    events = tuple(MATERIAL_EVENTS)

    arguments = GetMaterialEventsArguments.model_validate(
        {
            "corp_code": "00123456",
            "event_types": list(events),
            "bgn_de": "20250101",
            "end_de": "20251231",
        }
    )

    assert len(events) == 36
    assert arguments.event_types == events
