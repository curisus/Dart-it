from dataclasses import dataclass, field

from dart_crawler.dart_api import DartApi, RetryPolicy
from dart_crawler.http_client import HttpResponse


@dataclass
class FakeHttpClient:
    responses: list[HttpResponse]
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.requests.append((url, params))
        return self.responses.pop(0)

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
