from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from dart_crawler.api_models import DartListRow, FinancialAccount
from dart_crawler.attachments import AttachmentService
from dart_crawler.crawler_service import CrawlerService
from dart_crawler.dart_api import DartApi, FinancialQuery
from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpResponse
from dart_crawler.query_limits import LOCAL_QUERY_LIMITS, MAX_RESPONSE_ROWS
from dart_crawler.result import ErrorCode, Result, WarningCode, WarningInfo
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
    assert "export_report_excel" in listing.next_action
