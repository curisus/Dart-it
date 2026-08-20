"""OpenDART API adapter with typed parsing and bounded retries."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

import httpx2
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import ValidationError

from dart_crawler.api_models import (
    CompanyProfile,
    DartListResponse,
    DartListRow,
    DartRowsResponse,
    FinancialAccount,
    FinancialAccountResponse,
    FinancialIndexRow,
    MajorAccountRow,
)
from dart_crawler.http_client import HttpClient, HttpResponse
from dart_crawler.result import ErrorCode, ErrorInfo, JsonObject, Result, error_info

_OPEN_DART_BASE = "https://opendart.fss.or.kr/api"
_LIST_URL = f"{_OPEN_DART_BASE}/list.json"
_CORP_CODE_URL = f"{_OPEN_DART_BASE}/corpCode.xml"
_DOCUMENT_URL = f"{_OPEN_DART_BASE}/document.xml"
_FINANCIAL_ACCOUNT_URL = f"{_OPEN_DART_BASE}/fnlttSinglAcntAll.json"
_MAJOR_ACCOUNT_SINGLE_URL = f"{_OPEN_DART_BASE}/fnlttSinglAcnt.json"
_MAJOR_ACCOUNT_MULTI_URL = f"{_OPEN_DART_BASE}/fnlttMultiAcnt.json"
_FINANCIAL_INDEX_SINGLE_URL = f"{_OPEN_DART_BASE}/fnlttSinglIndx.json"
_FINANCIAL_INDEX_MULTI_URL = f"{_OPEN_DART_BASE}/fnlttCmpnyIndx.json"
_COMPANY_URL = f"{_OPEN_DART_BASE}/company.json"
_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do"
_VIEWER_DOCUMENT_URL = "https://dart.fss.or.kr/report/viewer.do"

# The registries (domains/report_topics.py, domains/ownership.py) own the
# set of valid endpoint names; this only guards against a malformed string
# reaching URL assembly.
_ENDPOINT_NAME_PATTERN: Final = re.compile(r"^[A-Za-z]+$", re.ASCII)

_DART_STATUS_ERRORS: Final[Mapping[str, tuple[ErrorCode, bool, str]]] = {
    "010": (ErrorCode.UPSTREAM_AUTH, False, "OpenDART API 키가 등록되지 않았습니다."),
    "011": (ErrorCode.UPSTREAM_AUTH, False, "OpenDART API 키를 사용할 수 없습니다."),
    "012": (ErrorCode.UPSTREAM_AUTH, False, "OpenDART 요청이 허용되지 않았습니다."),
    "013": (ErrorCode.NOT_FOUND, False, "OpenDART 조회 결과가 없습니다."),
    "014": (ErrorCode.NOT_FOUND, False, "OpenDART 파일을 찾을 수 없습니다."),
    "020": (ErrorCode.UPSTREAM_RATE_LIMIT, True, "OpenDART 호출 한도를 초과했습니다."),
    "800": (ErrorCode.UPSTREAM_UNAVAILABLE, True, "OpenDART 시스템을 점검 중입니다."),
    "900": (ErrorCode.UPSTREAM_UNAVAILABLE, True, "OpenDART 요청 형식이 올바르지 않습니다."),
    "901": (ErrorCode.UPSTREAM_AUTH, False, "OpenDART 요청 권한이 없습니다."),
}
_DEFAULT_DART_STATUS_ERROR: Final = (
    ErrorCode.UPSTREAM_UNAVAILABLE,
    True,
    "OpenDART가 요청을 처리하지 못했습니다.",
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry settings that can be replaced by deterministic tests."""

    max_retries: int = 3
    sleeper: Callable[[float], None] = time.sleep


@dataclass(frozen=True, slots=True)
class FinancialQuery:
    """Inputs for one official full-account comparison request."""

    corp_code: str
    business_year: int
    report_code: str
    statement_scope: str


class DartApi:
    """Small typed client for the OpenDART endpoints used by the server."""

    def __init__(
        self,
        http_client: HttpClient,
        *,
        api_key: str,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._retry_policy = retry_policy or RetryPolicy()

    def list_disclosures(
        self,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        """Return disclosure rows for one company and one regular-report type."""
        return self._fetch_rows(
            _LIST_URL,
            {
                "corp_code": corp_code,
                "bgn_de": "20150101",
                "end_de": time.strftime("%Y%m%d"),
                "pblntf_ty": "A",
                "pblntf_detail_ty": report_detail_type,
                "sort": "date",
                "sort_mth": "desc",
                "page_no": "1",
                "page_count": "100",
            },
            DartListResponse,
            unavailable_message="OpenDART 공시 검색에 실패했습니다.",
            parse_failure_message="OpenDART 공시 응답 형식을 해석할 수 없습니다.",
            unavailable_next_action="잠시 후 공시 검색을 다시 시도하세요.",
            parse_failure_next_action="OpenDART 응답 형식 변경 여부를 확인하세요.",
        )

    def find_disclosure(self, rcept_no: str) -> Result[DartListRow]:
        """Find one disclosure by its receipt number in the receipt-day window."""
        return self._find_disclosure_paged(rcept_no)

    def _find_disclosure_paged(self, rcept_no: str) -> Result[DartListRow]:
        receipt_date = rcept_no[:8]
        for detail_type in ("A001", "A002", "A003"):
            for page_no in range(1, 101):
                response = self._get_json(
                    _LIST_URL,
                    {
                        "bgn_de": receipt_date,
                        "end_de": receipt_date,
                        "pblntf_ty": "A",
                        "pblntf_detail_ty": detail_type,
                        "sort": "date",
                        "sort_mth": "desc",
                        "page_no": str(page_no),
                        "page_count": "100",
                    },
                )
                if not response.ok or response.data is None:
                    return Result.failure(
                        response.error
                        if response.error is not None
                        else error_info(
                            ErrorCode.UPSTREAM_UNAVAILABLE,
                            "접수번호 공시를 가져올 수 없습니다.",
                            retryable=True,
                        )
                    )
                try:
                    parsed = DartListResponse.model_validate_json(response.data.content)
                except ValidationError:
                    return Result.failure(
                        error_info(
                            ErrorCode.PARSE_FAILED,
                            "OpenDART 공시 응답 형식을 해석할 수 없습니다.",
                            retryable=False,
                        )
                    )
                if parsed.status == "013":
                    break
                if parsed.status != "000":
                    return Result.failure(_dart_status_error(parsed.status))
                for row in parsed.list:
                    if row.rcept_no == rcept_no:
                        return Result.success(row)
                if len(parsed.list) < 100:
                    break
        return Result.failure(
            error_info(
                ErrorCode.NOT_FOUND,
                "접수번호에 해당하는 정기공시를 찾지 못했습니다.",
                retryable=False,
            )
        )

    def download_company_codes(self) -> Result[bytes]:
        """Download the OpenDART company-code ZIP archive."""
        return self._get_bytes(_CORP_CODE_URL, {})

    def download_document(self, rcept_no: str) -> Result[bytes]:
        """Download one OpenDART original-document ZIP file."""
        return self._get_bytes(_DOCUMENT_URL, {"rcept_no": rcept_no})

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        """Fetch one DART viewer page without sending the OpenDART key."""
        return self._get_bytes(
            _VIEWER_URL,
            {"rcpNo": rcept_no},
            include_api_key=False,
        )

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        """Fetch one DART viewer iframe document by its document number."""
        page = self._get_bytes(
            _VIEWER_URL,
            {"rcpNo": rcept_no, "dcmNo": dcm_no},
            include_api_key=False,
        )
        if not page.ok or page.data is None:
            return Result.failure(
                page.error
                if page.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "DART 웹 문서를 수집할 수 없습니다.",
                    retryable=True,
                )
            )
        document_params = _viewer_document_params_list(page.data, rcept_no, dcm_no)
        if not document_params:
            document_params = (_viewer_document_params(page.data, rcept_no, dcm_no),)
        documents: list[bytes] = []
        for params in document_params:
            document = self._get_bytes(
                _VIEWER_DOCUMENT_URL,
                params,
                include_api_key=False,
            )
            if not document.ok or document.data is None:
                return Result.failure(
                    document.error
                    if document.error is not None
                    else error_info(
                        ErrorCode.UPSTREAM_UNAVAILABLE,
                        "DART viewer 문서를 수집할 수 없습니다.",
                        retryable=True,
                    )
                )
            if document.data:
                documents.append(document.data)
        if not documents:
            return Result.failure(
                error_info(
                    ErrorCode.UPSTREAM_LAYOUT_CHANGED,
                    "DART viewer 문서 구조를 해석할 수 없습니다.",
                    retryable=False,
                )
            )
        return Result.success(b"\n".join(documents))

    def fetch_financial_accounts(
        self,
        query: FinancialQuery,
    ) -> Result[tuple[FinancialAccount, ...]]:
        """Fetch OFS or CFS rows for one report period."""
        return self._fetch_rows(
            _FINANCIAL_ACCOUNT_URL,
            {
                "corp_code": query.corp_code,
                "bsns_year": str(query.business_year),
                "reprt_code": query.report_code,
                "fs_div": query.statement_scope,
            },
            FinancialAccountResponse,
            unavailable_message="OpenDART 전체 계정과목을 수집할 수 없습니다.",
            parse_failure_message="OpenDART 전체 계정과목 응답 형식을 해석할 수 없습니다.",
        )

    def fetch_major_accounts(
        self,
        corp_codes: tuple[str, ...],
        business_year: int,
        report_code: str,
    ) -> Result[tuple[MajorAccountRow, ...]]:
        """Fetch DS003 major-account rows for one or more companies."""
        single = len(corp_codes) == 1
        return self._fetch_rows(
            _MAJOR_ACCOUNT_SINGLE_URL if single else _MAJOR_ACCOUNT_MULTI_URL,
            {
                "corp_code": corp_codes[0] if single else ",".join(corp_codes),
                "bsns_year": str(business_year),
                "reprt_code": report_code,
            },
            DartRowsResponse[MajorAccountRow],
            unavailable_message="OpenDART 주요계정 재무정보를 수집할 수 없습니다.",
            parse_failure_message="OpenDART 주요계정 재무정보 응답 형식을 해석할 수 없습니다.",
        )

    def fetch_financial_indexes(
        self,
        corp_codes: tuple[str, ...],
        business_year: int,
        report_code: str,
        index_class: str,
    ) -> Result[tuple[FinancialIndexRow, ...]]:
        """Fetch DS003 financial-index rows for one or more companies."""
        single = len(corp_codes) == 1
        return self._fetch_rows(
            _FINANCIAL_INDEX_SINGLE_URL if single else _FINANCIAL_INDEX_MULTI_URL,
            {
                "corp_code": corp_codes[0] if single else ",".join(corp_codes),
                "bsns_year": str(business_year),
                "reprt_code": report_code,
                "idx_cl_code": index_class,
            },
            DartRowsResponse[FinancialIndexRow],
            unavailable_message="OpenDART 재무지표를 수집할 수 없습니다.",
            parse_failure_message="OpenDART 재무지표 응답 형식을 해석할 수 없습니다.",
        )

    def fetch_report_topic_rows(
        self,
        endpoint: str,
        corp_code: str,
        business_year: int,
        report_code: str,
    ) -> Result[tuple[JsonObject, ...]]:
        """Fetch DS002 regular-report key-information rows for one topic."""
        if _ENDPOINT_NAME_PATTERN.match(endpoint) is None:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "정기보고서 주요정보 endpoint 형식이 올바르지 않습니다.",
                    retryable=False,
                    details={"endpoint": endpoint},
                )
            )
        return self._fetch_rows(
            f"{_OPEN_DART_BASE}/{endpoint}.json",
            {
                "corp_code": corp_code,
                "bsns_year": str(business_year),
                "reprt_code": report_code,
            },
            DartRowsResponse[JsonObject],
            unavailable_message="OpenDART 정기보고서 주요정보를 수집할 수 없습니다.",
            parse_failure_message=(
                "OpenDART 정기보고서 주요정보 응답 형식을 해석할 수 없습니다."
            ),
        )

    def fetch_material_event_rows(
        self,
        endpoint: str,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> Result[tuple[JsonObject, ...]]:
        """Fetch DS005 주요사항보고 rows for one event type and receipt-date range."""
        if _ENDPOINT_NAME_PATTERN.match(endpoint) is None:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "주요사항보고 endpoint 형식이 올바르지 않습니다.",
                    retryable=False,
                    details={"endpoint": endpoint},
                )
            )
        return self._fetch_rows(
            f"{_OPEN_DART_BASE}/{endpoint}.json",
            {"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de},
            DartRowsResponse[JsonObject],
            unavailable_message="OpenDART 주요사항보고 정보를 수집할 수 없습니다.",
            parse_failure_message="OpenDART 주요사항보고 응답 형식을 해석할 수 없습니다.",
        )

    def fetch_company_profile(self, corp_code: str) -> Result[CompanyProfile]:
        """Fetch OpenDART DS001 company master data (company.json) for one company.

        company.json returns its payload fields at the top level beside
        status/message rather than under a `list`, so this does not go
        through the shared `_fetch_rows` rows-envelope path.
        """
        response = self._get_json(_COMPANY_URL, {"corp_code": corp_code})
        if not response.ok or response.data is None:
            return Result.failure(
                response.error
                if response.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 기업개황을 수집할 수 없습니다.",
                    retryable=True,
                ),
                warnings=response.warnings,
            )
        try:
            parsed = CompanyProfile.model_validate_json(response.data.content)
        except ValidationError:
            return Result.failure(
                error_info(
                    ErrorCode.PARSE_FAILED,
                    "OpenDART 기업개황 응답 형식을 해석할 수 없습니다.",
                    retryable=False,
                )
            )
        if parsed.status != "000":
            return Result.failure(_dart_status_error(parsed.status))
        return Result.success(parsed)

    def fetch_ownership_rows(
        self,
        endpoint: str,
        corp_code: str,
    ) -> Result[tuple[JsonObject, ...]]:
        """Fetch DS004 ownership-disclosure rows (majorstock/elestock) for one company."""
        if _ENDPOINT_NAME_PATTERN.match(endpoint) is None:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "지분공시 endpoint 형식이 올바르지 않습니다.",
                    retryable=False,
                    details={"endpoint": endpoint},
                )
            )
        return self._fetch_rows(
            f"{_OPEN_DART_BASE}/{endpoint}.json",
            {"corp_code": corp_code},
            DartRowsResponse[JsonObject],
            unavailable_message="OpenDART 지분공시 정보를 수집할 수 없습니다.",
            parse_failure_message="OpenDART 지분공시 정보 응답 형식을 해석할 수 없습니다.",
        )

    def _fetch_rows[RowT](
        self,
        url: str,
        params: Mapping[str, str],
        response_model: type[DartRowsResponse[RowT]],
        *,
        unavailable_message: str,
        parse_failure_message: str,
        unavailable_next_action: str | None = None,
        parse_failure_next_action: str | None = None,
    ) -> Result[tuple[RowT, ...]]:
        """GET one OpenDART rows endpoint and parse its `list` field."""
        response = self._get_json(url, params)
        if not response.ok or response.data is None:
            return Result.failure(
                response.error
                if response.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    unavailable_message,
                    retryable=True,
                ),
                warnings=response.warnings,
                next_action=unavailable_next_action,
            )
        try:
            parsed = response_model.model_validate_json(response.data.content)
        except ValidationError:
            return Result.failure(
                error_info(
                    ErrorCode.PARSE_FAILED,
                    parse_failure_message,
                    retryable=False,
                ),
                next_action=parse_failure_next_action,
            )
        if parsed.status != "000":
            return Result.failure(_dart_status_error(parsed.status))
        return Result.success(parsed.list)

    def _get_json(
        self,
        url: str,
        params: Mapping[str, str],
    ) -> Result[HttpResponse]:
        return self._request(url, params)

    def _get_bytes(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        include_api_key: bool = True,
    ) -> Result[bytes]:
        response = self._request(url, params, include_api_key=include_api_key)
        if not response.ok or response.data is None:
            return Result.failure(
                response.error
                if response.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "OpenDART 파일 수집에 실패했습니다.",
                    retryable=True,
                ),
                next_action="잠시 후 파일 수집을 다시 시도하세요.",
            )
        status_document = _dart_status_document(response.data.content)
        if status_document is not None:
            return Result.failure(_dart_status_error(status_document))
        return Result.success(response.data.content)

    def _request(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        include_api_key: bool = True,
    ) -> Result[HttpResponse]:
        request_params = (
            {"crtfc_key": self._api_key, **params} if include_api_key else dict(params)
        )
        for attempt in range(self._retry_policy.max_retries + 1):
            try:
                response = self._http_client.get(url, params=request_params)
            except httpx2.TransportError:
                if attempt >= self._retry_policy.max_retries:
                    return Result.failure(
                        error_info(
                            ErrorCode.UPSTREAM_UNAVAILABLE,
                            "OpenDART에 연결할 수 없습니다.",
                            retryable=True,
                        ),
                        next_action="네트워크 상태를 확인하고 다시 시도하세요.",
                    )
                self._retry_policy.sleeper(float(2**attempt))
                continue

            status_error = _http_status_error(response)
            if status_error is None:
                return Result.success(response)
            if not _can_retry(response, attempt, self._retry_policy.max_retries):
                return Result.failure(
                    status_error,
                    next_action="응답 오류를 확인하고 입력 또는 인증 설정을 수정하세요.",
                )
            self._retry_policy.sleeper(_retry_delay(response, attempt))
        return Result.failure(
            error_info(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "OpenDART 요청이 재시도 한도를 초과했습니다.",
                retryable=True,
            )
        )


def _http_status_error(response: HttpResponse) -> ErrorInfo | None:
    if response.status_code < 400:
        return None
    if response.status_code in (401, 403):
        return error_info(
            ErrorCode.UPSTREAM_AUTH,
            "OpenDART 인증에 실패했습니다.",
            retryable=False,
            details={"status_code": response.status_code},
        )
    if response.status_code == 404:
        return error_info(
            ErrorCode.NOT_FOUND,
            "OpenDART 자료를 찾을 수 없습니다.",
            retryable=False,
            details={"status_code": response.status_code},
        )
    if response.status_code == 429:
        return error_info(
            ErrorCode.UPSTREAM_RATE_LIMIT,
            "OpenDART 호출 한도를 초과했습니다.",
            retryable=True,
            details={"status_code": response.status_code},
        )
    return error_info(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "OpenDART 서버가 요청을 처리하지 못했습니다.",
        retryable=True,
        details={"status_code": response.status_code},
    )


def _can_retry(response: HttpResponse, attempt: int, max_retries: int) -> bool:
    return response.status_code >= 429 and attempt < max_retries


def _retry_delay(response: HttpResponse, attempt: int) -> float:
    raw_retry_after = response.headers.get("Retry-After")
    if raw_retry_after is not None:
        try:
            return max(0.0, float(raw_retry_after))
        except ValueError:
            pass
    return float(2**attempt)


def _dart_status_error(status: str) -> ErrorInfo:
    code, retryable, message = _DART_STATUS_ERRORS.get(
        status,
        _DEFAULT_DART_STATUS_ERROR,
    )
    return error_info(
        code,
        message,
        retryable=retryable,
        details={"dart_status": status},
    )


def _dart_status_document(content: bytes) -> str | None:
    """Parse a DART status XML by structure while leaving ZIP bytes untouched."""
    if content.startswith(b"PK"):
        return None
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException):
        return None
    if root.tag.rsplit("}", maxsplit=1)[-1] != "result":
        return None
    status_element = next(
        (
            child
            for child in root
            if child.tag.rsplit("}", maxsplit=1)[-1] == "status"
        ),
        None,
    )
    if status_element is None:
        return None
    return (status_element.text or "").strip()


def _viewer_document_params(
    content: bytes, rcept_no: str, dcm_no: str
) -> dict[str, str]:
    params = _viewer_document_params_list(content, rcept_no, dcm_no)
    if params:
        return params[0]
    text = content.decode("utf-8", errors="replace")
    pattern = re.compile(
        r"viewDoc\(\s*[\"'](?P<rcp>\d{14})[\"']\s*,\s*"
        r"[\"'](?P<dcm>\d+)[\"']\s*,\s*[\"'](?P<ele>[^\"']*)[\"']\s*,\s*"
        r"[\"'](?P<offset>[^\"']*)[\"']\s*,\s*[\"'](?P<length>[^\"']*)[\"']\s*,\s*"
        r"[\"'](?P<dtd>[^\"']*)[\"']\s*,\s*[\"'](?P<toc>[^\"']*)[\"']",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        if match.group("rcp") == rcept_no and match.group("dcm") == dcm_no:
            return {
                "rcpNo": rcept_no,
                "dcmNo": dcm_no,
                "eleId": match.group("ele"),
                "offset": match.group("offset"),
                "length": match.group("length"),
                "dtd": match.group("dtd"),
            }
    return {"rcpNo": rcept_no, "dcmNo": dcm_no}


def _viewer_document_params_list(
    content: bytes, rcept_no: str, dcm_no: str
) -> tuple[dict[str, str], ...]:
    text = content.decode("utf-8", errors="replace")
    assignment_pattern = re.compile(
        r"(?P<node>node\d+)\['(?P<field>dcmNo|eleId|offset|length|dtd|tocNo)'\]"
        r"\s*=\s*[\"'](?P<value>[^\"']*)[\"']",
        flags=re.IGNORECASE,
    )
    current: dict[str, dict[str, str]] = {}
    records: list[dict[str, str]] = []
    for match in assignment_pattern.finditer(text):
        node = match.group("node")
        field = match.group("field")
        if field.casefold() == "dcmno" and node in current:
            records.append(current[node])
            current[node] = {}
        current.setdefault(node, {})[field.casefold()] = match.group("value")
    records.extend(current.values())

    params: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        if record.get("dcmno") != dcm_no:
            continue
        required = ("eleid", "offset", "length", "dtd")
        if any(field not in record for field in required):
            continue
        key = tuple(record[field] for field in ("dcmno", *required))
        if key in seen:
            continue
        seen.add(key)
        params.append(
            {
                "rcpNo": rcept_no,
                "dcmNo": dcm_no,
                "eleId": record["eleid"],
                "offset": record["offset"],
                "length": record["length"],
                "dtd": record["dtd"],
            }
        )
    return tuple(params)
