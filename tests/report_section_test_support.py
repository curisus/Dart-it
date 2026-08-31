import pytest
from pydantic import SecretStr

from dart_crawler.api_models import DartListRow
from dart_crawler.attachments import AttachmentService
from dart_crawler.crawler_service import CrawlerService
from dart_crawler.dart_api import DartApi
from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpResponse
from dart_crawler.result import Result
from tests.remote_server_test_support import (
    ATTACHMENT_ID,
    RCEPT_NO,
    listed_attachment,
)

_OPINION = "<heading>독립된 감사인의 감사보고서</heading><p>적정의견을 표명합니다.</p>"
_BALANCE_SHEET = (
    "<heading>재무상태표</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>자산총계</td><td>1,000</td></tr></table>"
)
_INCOME = (
    "<heading>손익계산서</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>매출액</td><td>500</td></tr></table>"
)
_EQUITY = (
    "<heading>자본변동표</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>자본총계</td><td>800</td></tr></table>"
)
_CASH_FLOW = (
    "<heading>현금흐름표</heading>"
    "<table><tr><td>계정</td><td>당기</td></tr>"
    "<tr><td>현금및현금성자산</td><td>200</td></tr></table>"
)


def report_xml(*, with_cash_flow: bool = True) -> bytes:
    sections = (_OPINION, _BALANCE_SHEET, _INCOME, _EQUITY) + (
        (_CASH_FLOW,) if with_cash_flow else ()
    )
    return f"<document>{''.join(sections)}</document>".encode()


class NetworkRejectingHttpClient:
    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        raise AssertionError((url, params))

    def close(self) -> None:
        return None


def _forbid_disclosure(_self: DartApi, rcept_no: str) -> Result[DartListRow]:
    raise AssertionError(rcept_no)


def service_reading(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> CrawlerService:
    def list_attachments(
        _self: AttachmentService,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        assert rcept_no == RCEPT_NO
        return Result.success((listed_attachment(),))

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        assert rcept_no == RCEPT_NO
        assert selection == listed_attachment()
        return Result.success(content)

    monkeypatch.setattr(DartApi, "find_disclosure", _forbid_disclosure)
    monkeypatch.setattr(AttachmentService, "list", list_attachments)
    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)
    return CrawlerService(SecretStr("test-key"), NetworkRejectingHttpClient())


__all__ = [
    "ATTACHMENT_ID",
    "RCEPT_NO",
    "NetworkRejectingHttpClient",
    "report_xml",
    "service_reading",
]
