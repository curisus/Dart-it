from dataclasses import dataclass, field

from pydantic import SecretStr

from dart_crawler.excel_query_service import CrawlerServiceFactory
from dart_crawler.http_client import HttpResponse
from dart_crawler.query_limits import EXCEL_POLICY


@dataclass(frozen=True, slots=True)
class RouteRecordingHttpClient:
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.requests.append((url, params))
        if url.endswith("/list.json"):
            response_text = (
                '{"status":"000","message":"OK","list":[{"corp_cls":"Y",'
                '"corp_name":"삼성전자","corp_code":"00126380",'
                '"stock_code":"005930","report_nm":"사업보고서 (2025.12)",'
                '"rcept_no":"20260310002820","rcept_dt":"20260310","rm":""}]}'
            )
            return HttpResponse(200, {}, response_text.encode("utf-8"))
        status_text = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<result><status>800</status><message>blocked</message></result>"
        )
        return HttpResponse(200, {}, status_text.encode("utf-8"))

    def close(self) -> None:
        return None


def test_excel_factory_list_report_filings_uses_disclosure_list_without_company_archive() -> (
    None
):
    # Given
    http_client = RouteRecordingHttpClient()
    service = CrawlerServiceFactory(SecretStr("test-key"), http_client).create(
        EXCEL_POLICY
    )

    # When
    result = service.list_report_filings("00126380", "audit")

    # Then
    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 1
    assert result.data[0].company_name == "삼성전자"
    assert [request[0] for request in http_client.requests] == [
        "https://opendart.fss.or.kr/api/list.json"
    ]
    assert http_client.requests[0][1]["pblntf_detail_ty"] == "A001"
