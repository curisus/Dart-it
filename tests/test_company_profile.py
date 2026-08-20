from dataclasses import dataclass, field

from dart_crawler.api_models import CompanyProfile
from dart_crawler.domains.company_profile import CompanyProfileService
from dart_crawler.result import ErrorCode, Result, error_info


@dataclass(slots=True)
class RecordingCompanyProfileSource:
    """Hand-rolled CompanyProfileSource fake, recording every call it receives."""

    result: Result[CompanyProfile] | None = None
    calls: list[str] = field(default_factory=list)

    def fetch_company_profile(self, corp_code: str) -> Result[CompanyProfile]:
        self.calls.append(corp_code)
        assert self.result is not None
        return self.result


def _profile(**overrides: str) -> CompanyProfile:
    base: dict[str, str] = {
        "status": "000",
        "message": "OK",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
        "stock_name": "삼성전자",
        "stock_code": "005930",
        "ceo_nm": "한종희",
        "corp_cls": "Y",
        "jurir_no": "1301110006246",
        "bizr_no": "1248100998",
        "adres": "경기도 수원시 영통구 삼성로 129 (매탄동)",
        "hm_url": "www.samsung.com/sec",
        "ir_url": "www.samsung.com/sec/ir",
        "phn_no": "02-2255-0114",
        "fax_no": "031-200-7538",
        "induty_code": "264",
        "est_dt": "19690113",
        "acc_mt": "12",
    }
    base.update(overrides)
    return CompanyProfile.model_validate(base)


# --- success path ---------------------------------------------------------------


def test_get_maps_every_field_and_excludes_status_and_message() -> None:
    # Given
    source = RecordingCompanyProfileSource(result=Result.success(_profile()))
    service = CompanyProfileService(source)

    # When
    result = service.get("00126380")

    # Then
    assert result.ok is True
    assert result.data is not None
    dumped = result.data.model_dump()
    assert "status" not in dumped
    assert "message" not in dumped
    assert dumped == {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
        "stock_name": "삼성전자",
        "stock_code": "005930",
        "ceo_nm": "한종희",
        "corp_cls": "Y",
        "jurir_no": "1301110006246",
        "bizr_no": "1248100998",
        "adres": "경기도 수원시 영통구 삼성로 129 (매탄동)",
        "hm_url": "www.samsung.com/sec",
        "ir_url": "www.samsung.com/sec/ir",
        "phn_no": "02-2255-0114",
        "fax_no": "031-200-7538",
        "induty_code": "264",
        "est_dt": "19690113",
        "acc_mt": "12",
    }
    assert source.calls == ["00126380"]


# --- input guards -----------------------------------------------------------------


def test_get_rejects_a_malformed_corp_code_without_calling_source() -> None:
    # Given
    source = RecordingCompanyProfileSource()
    service = CompanyProfileService(source)

    # When
    result = service.get("not-8-digits")

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert result.next_action is not None
    assert source.calls == []


# --- upstream failure propagation -------------------------------------------------


def test_get_propagates_an_upstream_failure_unchanged() -> None:
    # Given
    upstream_failure = Result[CompanyProfile].failure(
        error_info(
            ErrorCode.UPSTREAM_AUTH,
            "OpenDART API 키가 등록되지 않았습니다.",
            retryable=False,
        ),
        next_action="키를 확인하세요.",
    )
    source = RecordingCompanyProfileSource(result=upstream_failure)
    service = CompanyProfileService(source)

    # When
    result = service.get("00126380")

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_AUTH
    assert result.next_action == "키를 확인하세요."
    assert source.calls == ["00126380"]
