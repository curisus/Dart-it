from dataclasses import dataclass, field
from io import BytesIO
from zipfile import ZipFile

import httpx2
import pytest

from dart_crawler.attachments import AttachmentService
from dart_crawler.dart_api import DartApi, FinancialQuery, RetryPolicy
from dart_crawler.http_client import HttpResponse
from dart_crawler.result import ErrorCode


@dataclass
class FakeHttpClient:
    responses: list[HttpResponse]
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.requests.append((url, params))
        return self.responses.pop(0)

    def close(self) -> None:
        return None


@dataclass
class DisconnectingHttpClient:
    calls: int = 0

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.calls += 1
        message = "Server disconnected without sending a response."
        raise httpx2.RemoteProtocolError(message)

    def close(self) -> None:
        return None


def test_list_request_honors_retry_after_and_parses_rows() -> None:
    response_text = (
        '{"status":"000","message":"OK","list":[{"corp_cls":"Y",'
        '"corp_name":"Sample","corp_code":"00126380","stock_code":"005930",'
        '"report_nm":"audit report","rcept_no":"20260310002820",'
        '"rcept_dt":"20260310","rm":""}]}'
    )
    client = FakeHttpClient(
        [
            HttpResponse(429, {"Retry-After": "0"}, b""),
            HttpResponse(200, {}, response_text.encode("utf-8")),
        ]
    )
    delays: list[float] = []
    api = DartApi(
        client,
        api_key="test-key",
        retry_policy=RetryPolicy(max_retries=3, sleeper=delays.append),
    )

    result = api.list_disclosures("00126380", "A001")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].corp_name == "Sample"
    assert delays == [0.0]
    assert client.requests[0][1]["crtfc_key"] == "test-key"


def test_auth_failure_does_not_retry() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"010","message":"bad key"}')]
    )
    delays: list[float] = []
    api = DartApi(
        client,
        api_key="test-key",
        retry_policy=RetryPolicy(max_retries=3, sleeper=delays.append),
    )

    result = api.list_disclosures("00126380", "A001")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "UPSTREAM_AUTH"
    assert delays == []


def test_server_disconnect_maps_to_upstream_unavailable_after_retries() -> None:
    client = DisconnectingHttpClient()
    delays: list[float] = []
    api = DartApi(
        client,
        api_key="test-key",
        retry_policy=RetryPolicy(max_retries=2, sleeper=delays.append),
    )

    result = api.list_disclosures("00126380", "A001")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_UNAVAILABLE
    assert result.error.retryable is True
    assert delays == [1.0, 2.0]
    assert client.calls == 3


def test_find_disclosure_paginates_receipt_day() -> None:
    row = (
        '{"corp_cls":"Y","corp_name":"Sample","corp_code":"00126380",'
        '"stock_code":"005930","report_nm":"분기보고서",'
        '"rcept_no":"20260515002181","rcept_dt":"20260515","rm":""}'
    )
    filler = row.replace("20260515002181", "20260515000001")
    first_page = (
        '{"status":"000","message":"OK","list":['
        + ",".join(filler for _ in range(100))
        + "]}"
    ).encode("utf-8")
    second_page = (
        '{"status":"000","message":"OK","list":[' + row + "]}"
    ).encode("utf-8")
    client = FakeHttpClient(
        [
            HttpResponse(200, {}, first_page),
            HttpResponse(200, {}, second_page),
        ]
    )
    api = DartApi(client, api_key="test-key")

    result = api.find_disclosure("20260515002181")

    assert result.ok is True
    assert result.data is not None
    assert result.data.rcept_no == "20260515002181"
    assert client.requests[0][1]["page_no"] == "1"
    assert client.requests[1][1]["page_no"] == "2"


def test_viewer_document_uses_attachment_page_parameters() -> None:
    page = (
        b'<script>viewDoc("20260515002181", "11386166", "1", '
        b'"1326", "2113", "dart4.xsd", "");</script>'
    )
    client = FakeHttpClient(
        [
            HttpResponse(200, {}, page),
            HttpResponse(200, {}, b"<html>report</html>"),
        ]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_viewer_document("20260515002181", "11386166")

    assert result.ok is True
    assert result.data == b"<html>report</html>"
    assert client.requests[0][1] == {
        "rcpNo": "20260515002181",
        "dcmNo": "11386166",
    }
    assert client.requests[1][1] == {
        "rcpNo": "20260515002181",
        "dcmNo": "11386166",
        "eleId": "1",
        "offset": "1326",
        "length": "2113",
        "dtd": "dart4.xsd",
    }


def test_document_download_reports_dart_status_error() -> None:
    status_error_body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<result><status>014</status>"
        "<message>\ud30c\uc77c\uc774 \uc874\uc7ac\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.</message></result>"
    ).encode("utf-8")
    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, "w") as archive:
        archive.writestr("document.xml", "<document />")
    zip_body = zip_buffer.getvalue()
    client = FakeHttpClient(
        [
            HttpResponse(200, {}, status_error_body),
            HttpResponse(200, {}, zip_body),
        ]
    )
    api = DartApi(client, api_key="test-key")

    missing = api.download_document("20260515001658")

    assert missing.ok is False, "DART status 014 must be reported as a failure"
    assert missing.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND

    archive_result = api.download_document("20260312001119")

    assert archive_result.ok is True
    assert archive_result.data == zip_body


def test_dart_status_message_is_not_exposed_in_serialized_result() -> None:
    sentinel = "UPSTREAM_SENTINEL_SECRET"
    status_error_body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<result><status>014</status><message>{sentinel}</message></result>"
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, status_error_body)])
    api = DartApi(client, api_key="test-key")

    result = api.download_document("20260515001658")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.details["dart_status"] == "014"
    assert sentinel not in result.model_dump_json()


def test_document_download_maps_status_document_without_message() -> None:
    status_error_body = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b"<result><status>014</status></result>"
    )
    api = DartApi(
        FakeHttpClient([HttpResponse(200, {}, status_error_body)]),
        api_key="test-key",
    )

    result = api.download_document("20260515001658")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.details["dart_status"] == "014"


def test_dart_status_message_is_not_copied_into_attachment_warning_details() -> None:
    sentinel = "UPSTREAM_WARNING_SENTINEL"
    status_error_body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<result><status>014</status><message>{sentinel}</message></result>"
    ).encode()
    viewer_html = (
        '<a href="/dsaf001/sub.do?rcpNo=20260515001658&amp;dcmNo=111">'
        "감사보고서</a>"
    ).encode()
    api = DartApi(
        FakeHttpClient(
            [
                HttpResponse(200, {}, status_error_body),
                HttpResponse(200, {}, viewer_html),
            ]
        ),
        api_key="test-key",
    )

    result = AttachmentService(api).list("20260515001658")

    assert result.ok is True
    assert result.data is not None
    assert result.error is None
    assert result.warnings[0].details["requested_zip_reason"] == (
        "OpenDART 파일을 찾을 수 없습니다."
    )
    assert sentinel not in result.model_dump_json()

@pytest.mark.parametrize(
    "status_body",
    [
        pytest.param(
            b"<result><status>014</status></result>",
            id="without_declaration",
        ),
        pytest.param(
            (
                b'<dart:result xmlns:dart="urn:dart">'
                b"<dart:status>014</dart:status>"
                b"</dart:result>"
            ),
            id="namespaced",
        ),
        pytest.param(
            b'<result version="1"><status>014</status></result>',
            id="root_attribute",
        ),
    ],
)
def test_document_download_detects_status_xml_by_shape(status_body: bytes) -> None:
    api = DartApi(
        FakeHttpClient([HttpResponse(200, {}, status_body)]),
        api_key="test-key",
    )

    result = api.download_document("20260515001658")

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.details["dart_status"] == "014"


def test_fetch_major_accounts_single_corp_hits_single_endpoint() -> None:
    body = (
        '{"status":"000","message":"OK","list":[{"rcept_no":"20260310002820",'
        '"reprt_code":"11011","bsns_year":"2025","corp_code":"00126380",'
        '"stock_code":"005930","fs_div":"CFS","fs_nm":"연결재무제표",'
        '"sj_div":"BS","sj_nm":"재무상태표","account_nm":"자산총계",'
        '"thstrm_amount":"1000","ord":"1","currency":"KRW"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_major_accounts(("00126380",), 2025, "11011")

    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 1
    row = result.data[0]
    assert row.account_nm == "자산총계"
    assert row.thstrm_amount == "1000"
    assert row.ord == "1"
    assert client.requests[0][0].endswith("fnlttSinglAcnt.json")
    assert client.requests[0][1]["corp_code"] == "00126380"
    assert client.requests[0][1]["bsns_year"] == "2025"
    assert client.requests[0][1]["reprt_code"] == "11011"


def test_fetch_major_accounts_multi_corp_hits_multi_endpoint_with_joined_codes() -> (
    None
):
    body = b'{"status":"000","message":"OK","list":[]}'
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_major_accounts(
        ("00126380", "00164742", "00164779"), 2025, "11011"
    )

    assert result.ok is True
    assert client.requests[0][0].endswith("fnlttMultiAcnt.json")
    assert client.requests[0][1]["corp_code"] == "00126380,00164742,00164779"


def test_fetch_financial_indexes_single_corp_passes_idx_cl_code() -> None:
    body = (
        '{"status":"000","message":"OK","list":[{"bsns_year":"2025",'
        '"corp_code":"00126380","stock_code":"005930","stlm_dt":"2025-12-31",'
        '"idx_cl_code":"M210000","idx_cl_nm":"수익성지표",'
        '"idx_nm":"매출총이익율","idx_val":"12.3"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_indexes(("00126380",), 2025, "11011", "M210000")

    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 1
    assert result.data[0].idx_val == "12.3"
    assert client.requests[0][0].endswith("fnlttSinglIndx.json")
    assert client.requests[0][1]["idx_cl_code"] == "M210000"


def test_fetch_financial_indexes_multi_corp_hits_multi_endpoint() -> None:
    body = b'{"status":"000","message":"OK","list":[]}'
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_indexes(
        ("00126380", "00164742"), 2025, "11011", "M210000"
    )

    assert result.ok is True
    assert client.requests[0][0].endswith("fnlttCmpnyIndx.json")
    assert client.requests[0][1]["corp_code"] == "00126380,00164742"


def test_fetch_financial_indexes_row_defaults_missing_idx_val() -> None:
    body = (
        '{"status":"000","message":"OK","list":[{"bsns_year":"2025",'
        '"corp_code":"00126380","stock_code":"005930","stlm_dt":"2025-12-31",'
        '"idx_cl_code":"M210000","idx_cl_nm":"수익성지표",'
        '"idx_nm":"매출총이익율"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_indexes(("00126380",), 2025, "11011", "M210000")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].idx_val == ""


def test_fetch_major_accounts_ignores_unknown_extra_fields() -> None:
    body = (
        '{"status":"000","message":"OK","list":[{"rcept_no":"20260310002820",'
        '"reprt_code":"11011","bsns_year":"2025","corp_code":"00126380",'
        '"fs_div":"CFS","sj_div":"BS","account_nm":"자산총계",'
        '"totally_unknown_field":"should be ignored"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_major_accounts(("00126380",), 2025, "11011")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].account_nm == "자산총계"


def test_fetch_major_accounts_not_found_status_maps_to_not_found() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"013","message":"no data"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_major_accounts(("00126380",), 2025, "11011")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_fetch_major_accounts_auth_failure_status_maps_to_upstream_auth() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"010","message":"bad key"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_major_accounts(("00126380",), 2025, "11011")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH


def test_fetch_financial_indexes_not_found_status_maps_to_not_found() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"013","message":"no data"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_indexes(("00126380",), 2025, "11011", "M210000")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_fetch_financial_indexes_auth_failure_status_maps_to_upstream_auth() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"010","message":"bad key"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_indexes(("00126380",), 2025, "11011", "M210000")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH


def test_fetch_major_accounts_malformed_json_maps_to_parse_failed() -> None:
    client = FakeHttpClient([HttpResponse(200, {}, b"not json at all")])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_major_accounts(("00126380",), 2025, "11011")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.PARSE_FAILED


def test_fetch_financial_indexes_malformed_json_maps_to_parse_failed() -> None:
    client = FakeHttpClient([HttpResponse(200, {}, b"not json at all")])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_indexes(("00126380",), 2025, "11011", "M210000")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.PARSE_FAILED


def test_document_download_returns_pk_payload_untouched() -> None:
    archive_body = b"PK\x03\x04<result><status>014</status></result>"
    api = DartApi(
        FakeHttpClient([HttpResponse(200, {}, archive_body)]),
        api_key="test-key",
    )

    result = api.download_document("20260515001658")

    assert result.ok is True
    assert result.data == archive_body
    assert result.error is None


def test_fetch_financial_accounts_parses_rows_without_fs_div() -> None:
    # fnlttSinglAcntAll rows do not echo the fs_div request parameter,
    # so a real-shape row without it must still parse (regression:
    # a required fs_div made every live payload fail with PARSE_FAILED).
    body = (
        '{"status":"000","message":"OK","list":[{"rcept_no":"20250311000001",'
        '"reprt_code":"11011","bsns_year":"2024","corp_code":"00126380",'
        '"sj_div":"BS","sj_nm":"재무상태표","account_id":"ifrs-full_Assets",'
        '"account_nm":"자산총계","account_detail":"-","thstrm_nm":"제 56 기",'
        '"thstrm_amount":"1000","frmtrm_nm":"제 55 기","frmtrm_amount":"900",'
        '"bfefrmtrm_nm":"제 54 기","bfefrmtrm_amount":"800","ord":"1",'
        '"currency":"KRW"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_financial_accounts(
        FinancialQuery(
            corp_code="00126380",
            business_year=2024,
            report_code="11011",
            statement_scope="OFS",
        )
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].fs_div == ""
    assert result.data[0].account_nm == "자산총계"
    assert result.data[0].bfefrmtrm_amount == "800"


# --- fetch_company_profile (DS001 company.json) -------------------------------


def test_fetch_company_profile_builds_url_and_parses_top_level_fields() -> None:
    body = (
        '{"status":"000","message":"OK","corp_code":"00126380",'
        '"corp_name":"삼성전자","corp_name_eng":"SAMSUNG ELECTRONICS CO,.LTD",'
        '"stock_name":"삼성전자","stock_code":"005930","ceo_nm":"한종희",'
        '"corp_cls":"Y","jurir_no":"1301110006246",'
        '"bizr_no":"1248100998","adres":"경기도 수원시 영통구 삼성로 129 (매탄동)",'
        '"hm_url":"www.samsung.com/sec","ir_url":"www.samsung.com/sec/ir",'
        '"phn_no":"02-2255-0114","fax_no":"031-200-7538",'
        '"induty_code":"264","est_dt":"19690113","acc_mt":"12"}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_company_profile("00126380")

    assert result.ok is True
    assert result.data is not None
    assert result.data.corp_name == "삼성전자"
    assert result.data.corp_name_eng == "SAMSUNG ELECTRONICS CO,.LTD"
    assert result.data.ceo_nm == "한종희"
    assert result.data.est_dt == "19690113"
    assert result.data.acc_mt == "12"
    assert client.requests[0][0].endswith("company.json")
    assert client.requests[0][1]["corp_code"] == "00126380"
    assert client.requests[0][1]["crtfc_key"] == "test-key"


def test_fetch_company_profile_not_found_status_maps_to_not_found() -> None:
    client = FakeHttpClient(
        [HttpResponse(200, {}, b'{"status":"013","message":"no data"}')]
    )
    api = DartApi(client, api_key="test-key")

    result = api.fetch_company_profile("00126380")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_fetch_company_profile_malformed_json_maps_to_parse_failed() -> None:
    client = FakeHttpClient([HttpResponse(200, {}, b"not json at all")])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_company_profile("00126380")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.PARSE_FAILED


# --- fetch_ownership_rows (DS004 majorstock/elestock) --------------------------


def test_fetch_ownership_rows_builds_url_for_major_holding_endpoint() -> None:
    body = b'{"status":"000","message":"OK","list":[]}'
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_ownership_rows("majorstock", "00126380")

    assert result.ok is True
    assert client.requests[0][0].endswith("majorstock.json")
    assert client.requests[0][1] == {"crtfc_key": "test-key", "corp_code": "00126380"}


def test_fetch_ownership_rows_builds_url_for_insider_ownership_endpoint() -> None:
    body = b'{"status":"000","message":"OK","list":[]}'
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_ownership_rows("elestock", "00126380")

    assert result.ok is True
    assert client.requests[0][0].endswith("elestock.json")
    assert client.requests[0][1] == {"crtfc_key": "test-key", "corp_code": "00126380"}


def test_fetch_ownership_rows_preserves_unknown_fields() -> None:
    body = (
        '{"status":"000","message":"OK","list":[{"corp_code":"00126380",'
        '"report_tp":"신규","totally_unknown_field":"kept"}]}'
    ).encode()
    client = FakeHttpClient([HttpResponse(200, {}, body)])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_ownership_rows("majorstock", "00126380")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0]["report_tp"] == "신규"
    assert result.data[0]["totally_unknown_field"] == "kept"


def test_fetch_ownership_rows_rejects_malformed_endpoint_without_http_call() -> None:
    # Given: an empty response list means any HTTP call would raise IndexError
    client = FakeHttpClient([])
    api = DartApi(client, api_key="test-key")

    result = api.fetch_ownership_rows("bad endpoint!", "00126380")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert client.requests == []
