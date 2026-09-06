from dart_crawler.excel_dataset_filename import dataset_filename
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.filename_safety import MAX_FILENAME_STEM_CHARS
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import JsonObject


def _dataset(
    domain: ExcelDataDomain,
    arguments: JsonObject,
) -> NormalizedExcelDataset:
    return NormalizedExcelDataset(
        domain=domain,
        validated_arguments=arguments,
        request_fingerprint="1" * 64,
        source_fingerprint="2" * 64,
        dataset_id="3" * 64,
        columns=("a",),
        rows=({"a": "1"},),
        provenance=NormalizedExcelProvenance(
            domain=domain,
            source_rows=1,
            normalized_rows=1,
        ),
        total_rows=1,
    )


def test_scalar_arguments_identify_one_filing_period() -> None:
    dataset = _dataset(
        ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
        {
            "corp_code": "00126380",
            "bsns_year": 2025,
            "reprt_code": "11011",
            "fs_div": "CFS",
        },
    )

    assert dataset_filename(dataset, 1) == (
        "get_financial_statements_00126380_2025_11011_CFS.xlsx"
    )
    assert dataset_filename(dataset, 2) == (
        "get_financial_statements_00126380_2025_11011_CFS_2.xlsx"
    )


def test_the_companies_a_batch_covers_reach_the_name() -> None:
    """For a multi-company domain the list argument is what tells files apart."""
    dataset = _dataset(
        ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        {
            "corp_codes": ["00126380", "00164779"],
            "bsns_year": 2025,
            "reprt_code": "11011",
        },
    )

    assert dataset_filename(dataset, 1) == (
        "get_major_accounts_00126380-00164779_2025_11011.xlsx"
    )


def test_a_long_list_says_how_many_more_it_covers() -> None:
    dataset = _dataset(
        ExcelDataDomain.GET_MAJOR_ACCOUNTS,
        {
            "corp_codes": ["00000001", "00000002", "00000003", "00000004"],
            "bsns_year": 2025,
            "reprt_code": "11011",
        },
    )

    assert dataset_filename(dataset, 1) == (
        "get_major_accounts_00000001-00000002-00000003-외1_2025_11011.xlsx"
    )


def test_an_oversized_argument_still_leaves_room_for_the_collision_suffix() -> None:
    """Otherwise every suffix trims to one name and publishing never settles."""
    dataset = _dataset(
        ExcelDataDomain.GET_FINANCIAL_STATEMENTS,
        {
            "corp_code": "0" * 500,
            "bsns_year": 10**300,
            "reprt_code": "1" * 500,
            "fs_div": "C" * 500,
        },
    )

    first = dataset_filename(dataset, 1)
    second = dataset_filename(dataset, 2)

    assert first != second
    assert second.endswith("_2.xlsx")
    assert len(first) <= MAX_FILENAME_STEM_CHARS + len(".xlsx")


def test_a_query_with_no_extra_arguments_keeps_the_domain_name() -> None:
    dataset = _dataset(
        ExcelDataDomain.SEARCH_COMPANIES,
        {"company_query": "삼성 전자", "report_kind": None},
    )

    assert dataset_filename(dataset, 1) == "search_companies_삼성_전자.xlsx"
