from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from dart_crawler import company_search
from dart_crawler.api_models import DartListRow, FinancialAccount
from dart_crawler.attachments import AttachmentService
from dart_crawler.company_name_matching import CompanyCode
from dart_crawler.company_search import CompanySearchService
from dart_crawler.crawler_service import CrawlerService
from dart_crawler.dart_api import DartApi, FinancialQuery
from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpResponse
from dart_crawler.query_limits import LOCAL_QUERY_LIMITS, MAX_RESPONSE_ROWS
from dart_crawler.result import ErrorCode, Result, WarningCode, WarningInfo
from tests.company_directory_fixtures import directory_archive
from tests.report_section_test_support import (
    ATTACHMENT_ID,
    RCEPT_NO,
    report_xml,
    service_reading,
)

_RCEPT_NO = "20260515001658"
_SOURCE_RCEPT_NO = "20260312001119"
_ATTACHMENT_ID = f"opendart:{_RCEPT_NO}:/{_SOURCE_RCEPT_NO}/audit.xml"
_REPORT_XML = "<document><title>감사보고서</title></document>".encode()


@dataclass(slots=True)
class RecordingHttpClient:
    """Fake HTTP client that records every attempted request."""

    requested_urls: list[str] = field(default_factory=list)
    responses: list[HttpResponse] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.requested_urls.append(url)
        if self.responses:
            return self.responses.pop(0)
        return HttpResponse(status_code=200, headers={}, content=b"")

    def close(self) -> None:
        return None


def _listed_attachment() -> Attachment:
    return Attachment(
        attachment_id=_ATTACHMENT_ID,
        rcept_no=_RCEPT_NO,
        source_rcept_no=_SOURCE_RCEPT_NO,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )


def _forbid_disclosure(_self: DartApi, rcept_no: str) -> Result[DartListRow]:
    raise AssertionError(rcept_no)


def _listing_warning() -> WarningInfo:
    return WarningInfo(
        code=WarningCode.ORIGINAL_FILING_SOURCE_USED,
        message="원본 공시에서 원문을 수집했습니다.",
    )


def test_export_without_output_dir_fails_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(DartApi, "find_disclosure", _forbid_disclosure)
    http_client = RecordingHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.export_report_excel(_RCEPT_NO, _ATTACHMENT_ID)

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.CONFIG_ERROR
    assert result.error.retryable is False
    assert result.next_action is not None
    assert http_client.requested_urls == []


def test_load_parsed_document_carries_listing_metadata_and_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    listing_warning = _listing_warning()
    listed = _listed_attachment()
    selections: list[str | Attachment] = []

    def list_attachments(
        _self: AttachmentService,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        assert rcept_no == _RCEPT_NO
        return Result.success((listed,), warnings=(listing_warning,))

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        assert rcept_no == _RCEPT_NO
        selections.append(selection)
        return Result.success(_REPORT_XML)

    monkeypatch.setattr(DartApi, "find_disclosure", _forbid_disclosure)
    monkeypatch.setattr(AttachmentService, "list", list_attachments)
    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)
    http_client = RecordingHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    loaded = service._load_parsed_document(_RCEPT_NO, _ATTACHMENT_ID)

    # Then
    assert loaded.ok is True
    assert loaded.data is not None
    assert loaded.data.attachment_title == "별도감사보고서"
    assert loaded.data.source_rcept_no == _SOURCE_RCEPT_NO
    assert loaded.data.document.sections
    assert loaded.warnings == (listing_warning,)
    assert selections == [listed]
    assert http_client.requested_urls == []


def test_load_parsed_document_rejects_identifier_missing_from_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    listing_warning = _listing_warning()

    def list_attachments(
        _self: AttachmentService,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        assert rcept_no == _RCEPT_NO
        return Result.success((_listed_attachment(),), warnings=(listing_warning,))

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        raise AssertionError((rcept_no, selection))

    monkeypatch.setattr(DartApi, "find_disclosure", _forbid_disclosure)
    monkeypatch.setattr(AttachmentService, "list", list_attachments)
    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)
    service = CrawlerService(SecretStr("test-key"), RecordingHttpClient())

    # When
    loaded = service._load_parsed_document(
        _RCEPT_NO,
        f"opendart:{_RCEPT_NO}:unlisted.xml",
    )

    # Then
    assert loaded.ok is False
    assert loaded.data is None
    assert loaded.error is not None
    assert loaded.error.code is ErrorCode.INVALID_INPUT
    assert loaded.warnings == (listing_warning,)
    assert "list_report_attachments" in (loaded.next_action or "")


def test_get_registration_statements_delegates_to_ds006_endpoint() -> None:
    response_body = (
        b'{"status":"000","message":"OK","group":[{"title":"'
        b'\xec\x9d\xbc\xeb\xb0\x98\xec\x82\xac\xed\x95\xad",'
        b'"list":[{"corp_code":"00126380","rcept_no":"20240115000123"}]}]}'
    )
    http_client = RecordingHttpClient()
    http_client.responses = [HttpResponse(200, {}, response_body)]
    service = CrawlerService(SecretStr("test-key"), http_client)

    result = service.get_registration_statements(
        "00126380",
        "equity_securities",
        "20240101",
        "20241231",
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.groups[0].title == "일반사항"
    assert http_client.requested_urls == ["https://opendart.fss.or.kr/api/estkRs.json"]


def test_local_query_limits_reach_financial_domain_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    accounts = tuple(
        FinancialAccount(
            sj_div="BS",
            bsns_year="2023",
            reprt_code="11011",
            account_id=f"account-{index}",
            account_nm="자산총계",
        )
        for index in range(MAX_RESPONSE_ROWS + 1)
    )

    def fetch_accounts(
        _self: DartApi,
        query: FinancialQuery,
    ) -> Result[tuple[FinancialAccount, ...]]:
        del query
        return Result.success(accounts)

    monkeypatch.setattr(DartApi, "fetch_financial_accounts", fetch_accounts)
    service = CrawlerService(
        SecretStr("test-key"),
        RecordingHttpClient(),
        limits=LOCAL_QUERY_LIMITS,
    )

    # When
    result = service.get_financial_statements("00126380", 2023, "11011", "OFS")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.returned_row_count == MAX_RESPONSE_ROWS + 1


def test_each_discovery_step_points_at_the_next_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The four tools run in one order and each answer holds the next argument."""
    service = service_reading(monkeypatch, report_xml())

    listing = service.list_report_sections(RCEPT_NO, ATTACHMENT_ID)

    assert listing.ok is True
    assert listing.next_action is not None
    assert "get_report_sections" in listing.next_action
    # The remote surface registers no export tool, and both surfaces share this
    # text, so it must never name one.
    assert "export_report_excel" not in listing.next_action


_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_DIRECTORY_ARCHIVE = directory_archive(
    (
        CompanyCode("00126380", "Sample Holdings", "005930"),
        CompanyCode("00126381", "Sample Holdings Bio", None),
    )
)
_AUDIT_LIST_JSON = (
    '{"status":"000","message":"OK","list":[{"corp_cls":"Y",'
    '"corp_name":"보고서상 회사명","corp_code":"00126380",'
    '"stock_code":"005930","report_nm":"감사보고서 (2025.12)",'
    '"rcept_no":"20260310002820","rcept_dt":"20260310","rm":""}]}'
)


@dataclass(slots=True)
class DirectoryHttpClient:
    """Fake OpenDART serving the company directory and one disclosure list."""

    directory: HttpResponse = field(
        default_factory=lambda: HttpResponse(200, {}, _DIRECTORY_ARCHIVE)
    )
    listing: str = _AUDIT_LIST_JSON
    requested_urls: list[str] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        del params
        self.requested_urls.append(url)
        if url == _CORP_CODE_URL:
            return self.directory
        if url == _LIST_URL:
            return HttpResponse(200, {}, self.listing.encode())
        raise AssertionError(url)

    def close(self) -> None:
        return None


def _forbid_ranking(*_args: object, **_kwargs: object) -> object:
    raise AssertionError


def test_list_report_filings_names_the_company_from_the_cached_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: neither a ranked search nor its per-candidate filing checks run
    monkeypatch.setattr(company_search, "_top_ranked", _forbid_ranking)
    monkeypatch.setattr(CompanySearchService, "search", _forbid_ranking)
    http_client = DirectoryHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    first = service.list_report_filings("00126380", "audit")
    second = service.list_report_filings("00126380", "audit")

    # Then
    for result in (first, second):
        assert result.ok is True
        assert result.data is not None
        assert [filing.company_name for filing in result.data] == ["Sample Holdings"]
    assert http_client.requested_urls == [_CORP_CODE_URL, _LIST_URL, _LIST_URL]


def test_list_report_filings_rejects_an_unknown_corp_code_without_a_list_call() -> (
    None
):
    # Given
    http_client = DirectoryHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings("99999999", "audit")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.message == "회사코드에 해당하는 회사를 찾지 못했습니다."
    assert result.next_action == "회사코드와 보고서 종류를 확인하세요."
    assert http_client.requested_urls == [_CORP_CODE_URL]


def test_list_report_filings_returns_the_directory_failure() -> None:
    # Given
    http_client = DirectoryHttpClient(directory=HttpResponse(401, {}, b""))
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings("00126380", "audit")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH
    assert result.next_action == "회사코드와 보고서 종류를 확인하세요."
    assert http_client.requested_urls == [_CORP_CODE_URL]


def test_list_report_filings_rejects_a_report_kind_before_any_request() -> None:
    # Given
    http_client = DirectoryHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings("00126380", "unsupported")

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert http_client.requested_urls == []


_EMPTY_LIST_JSON = '{"status":"000","message":"OK","list":[]}'
_HALF_YEAR_LIST_JSON = (
    '{"status":"000","message":"OK","list":[{"corp_cls":"Y",'
    '"corp_name":"보고서상 회사명","corp_code":"00126380",'
    '"stock_code":"005930","report_nm":"반기보고서 (2025.06)",'
    '"rcept_no":"20250814002820","rcept_dt":"20250814","rm":""}]}'
)


@pytest.mark.parametrize("corp_code", ["", "   "])
@pytest.mark.parametrize("directory_status", [200, 401])
def test_list_report_filings_refuses_an_empty_corp_code_without_any_request(
    corp_code: str, directory_status: int
) -> None:
    # Given: the directory would answer (200) or fail (401) if it were asked
    http_client = DirectoryHttpClient(
        directory=HttpResponse(directory_status, {}, _DIRECTORY_ARCHIVE)
    )
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings(corp_code, "audit")

    # Then: the envelope the ranked lookup gave an empty query
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.error.message == "회사 검색어가 비어 있습니다."
    assert result.error.retryable is False
    assert result.warnings == ()
    assert result.next_action == "회사코드와 보고서 종류를 확인하세요."
    assert http_client.requested_urls == []


def test_list_report_filings_checks_the_report_kind_before_an_empty_corp_code() -> None:
    # Given
    http_client = DirectoryHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings("", "unsupported")

    # Then
    assert result.error is not None
    assert result.error.message == "report_kind가 지원 범위에 없습니다."
    assert http_client.requested_urls == []


@pytest.mark.parametrize(
    "listing",
    [_EMPTY_LIST_JSON, _HALF_YEAR_LIST_JSON],
    ids=["no_disclosure", "half_year_only"],
)
def test_list_report_filings_reports_a_company_without_the_report_kind(
    listing: str,
) -> None:
    # Given: the company is in the directory but has no audit filing
    http_client = DirectoryHttpClient(listing=listing)
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings("00126380", "audit")

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.message == "대상 보고서가 존재하는 회사를 찾지 못했습니다."
    assert result.error.retryable is False
    assert result.warnings == ()
    assert result.next_action == "회사코드와 보고서 종류를 확인하세요."
    assert http_client.requested_urls == [_CORP_CODE_URL, _LIST_URL]


def test_list_report_filings_passes_a_filing_list_failure_through() -> None:
    # Given: OpenDART answers the disclosure search with "no data" (013)
    http_client = DirectoryHttpClient(
        listing='{"status":"013","message":"조회된 데이타가 없습니다."}'
    )
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.list_report_filings("00126380", "audit")

    # Then: the filing service's own failure, not the missing-report envelope
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.message == "OpenDART 조회 결과가 없습니다."
    assert result.next_action == "잠시 후 공시 목록을 다시 요청하세요."
