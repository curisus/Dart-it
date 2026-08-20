"""Live validation client for the remote DART MCP data service.

The script drives the running server over raw JSON-RPC, then re-derives the same
attachment locally through the public parsing API and compares the two cell by
cell. Nothing here is asserted from reading code: every line it prints is backed
by a value received in this run. The OpenDART key is read from the client
environment only and is never printed.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, NoReturn

import httpx2

from dart_crawler.attachments import AttachmentService
from dart_crawler.dart_api import DartApi
from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
)
from dart_crawler.document_parser import parse_attachment
from dart_crawler.document_validation import validate_document
from dart_crawler.domain import Attachment
from dart_crawler.http_client import HttpxClient
from dart_crawler.result import Result
from dart_crawler.section_models import MAX_RESPONSE_CELLS, section_id
from dart_crawler.statement_lexicon import compact
from dart_crawler.value_parser import parse_cell_value

# The Excel path's expectation builder is private, but comparing against it is
# the point: feeding it both documents proves the data path carries exactly the
# facts the workbook writer would have written.
from dart_crawler.workbook_validation import (
    CellCoordinate,
    CellValue,
    _sheet_expectations,
)

_DEFAULT_URL: Final = "http://127.0.0.1:8765/api/mcp"
_ACCEPT: Final = "application/json, text/event-stream"
_KEY_HEADER: Final = "X-OpenDART-API-Key"
_ENV_KEY_NAME: Final = "OPEN_DART_API_KEY"
_ACCOUNTS_URL: Final = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
_ANNUAL_REPORT_CODE: Final = "11011"
_SEPARATE_SCOPE: Final = "OFS"
_BALANCE_SHEET_DIVISION: Final = "BS"
# One batch stays under the server's own selection guard, so a rejected batch
# would mean the guard moved rather than that the script asked for too much.
_BATCH_CELL_LIMIT: Final = MAX_RESPONSE_CELLS - 2_000
_OFFICIAL_ACCOUNT_NAMES: Final = ("자산총계", "부채총계", "자본총계")
# A Korean statement states amounts in won, thousands, millions, or 억; the
# official API always answers in won, so a match is exact after one scaling.
_SCALE_FACTORS: Final = (1, 1_000, 1_000_000, 100_000_000)
_STATEMENTS_ALIAS: Final = "statements"
_NOTE_KIND: Final = "note"
_BALANCE_SHEET_KIND: Final = "balance_sheet"


class LiveValidationError(RuntimeError):
    """A live step could not continue with the response it received."""


def _abort(message: str) -> NoReturn:
    """Stop the run so every call site fails with one consistent type."""
    raise LiveValidationError(message)


def _as_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _abort(f"{label}: 객체가 아닌 값을 받았습니다 ({type(value).__name__}).")
    return {str(key): item for key, item in value.items()}


def _as_array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        _abort(f"{label}: 배열이 아닌 값을 받았습니다 ({type(value).__name__}).")
    return list(value)


def _as_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        _abort(f"{label}: 문자열이 아닌 값을 받았습니다 ({type(value).__name__}).")
    return value


def _as_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _abort(f"{label}: 정수가 아닌 값을 받았습니다 ({type(value).__name__}).")
    return value


@dataclass(frozen=True, slots=True)
class Check:
    """One named assertion with the observed detail that decided it."""

    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class Recorder:
    """Collects the checks, timings, and facts that the summary reports."""

    checks: list[Check] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    facts: dict[str, object] = field(default_factory=dict)

    def record(self, name: str, *, passed: bool, detail: str) -> bool:
        """Record and print one check, returning whether it passed."""
        self.checks.append(Check(name=name, passed=passed, detail=detail))
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        return passed

    def time(self, label: str, seconds: float) -> None:
        """Record the wall time of one request under a unique label."""
        self.timings[label] = round(seconds, 3)
        print(f"       ({label} {seconds:.2f}s)")

    @property
    def passed(self) -> bool:
        """Whether every recorded check passed."""
        return all(check.passed for check in self.checks)


class RemoteClient:
    """Raw JSON-RPC caller for one remote MCP endpoint."""

    def __init__(self, url: str, api_key: str, recorder: Recorder) -> None:
        self._url = url
        self._api_key = api_key
        self._recorder = recorder
        self._request_id = 0
        self._client = httpx2.Client(
            timeout=httpx2.Timeout(connect=5.0, read=600.0, write=30.0, pool=30.0),
        )

    def close(self) -> None:
        """Release the connection pool."""
        self._client.close()

    def __enter__(self) -> RemoteClient:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    def list_tools(self) -> tuple[str, ...]:
        """Return the tool names the server advertises, asking without a key."""
        body = self._post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list"},
            auth="none",
            label="tools/list",
        )
        result = _as_object(body.get("result"), "tools/list result")
        tools = _as_array(result.get("tools"), "tools")
        return tuple(
            _as_text(_as_object(tool, "tool").get("name"), "tool name")
            for tool in tools
        )

    def call(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        auth: str = "header",
        label: str | None = None,
    ) -> dict[str, object]:
        """Call one tool and return its Result envelope."""
        body = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            auth=auth,
            label=label or name,
        )
        return _envelope(body)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _post(
        self,
        payload: dict[str, object],
        *,
        auth: str,
        label: str,
    ) -> dict[str, object]:
        headers = {"Content-Type": "application/json", "Accept": _ACCEPT}
        if auth == "header":
            headers[_KEY_HEADER] = self._api_key
        elif auth == "bearer":
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = time.perf_counter()
        response = self._client.post(self._url, json=payload, headers=headers)
        self._recorder.time(label, time.perf_counter() - started)
        if response.status_code != 200:
            _abort(f"{label}: HTTP {response.status_code} 응답을 받았습니다.")
        return _as_object(response.json(), f"{label} 응답")


def _envelope(body: dict[str, object]) -> dict[str, object]:
    """Extract the tool's Result envelope from one JSON-RPC response body."""
    if "error" in body:
        _abort(f"JSON-RPC 오류: {json.dumps(body['error'], ensure_ascii=False)}")
    result = _as_object(body.get("result"), "tools/call result")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return _unwrapped(_as_object(structured, "structuredContent"))
    content = _as_array(result.get("content"), "content")
    for item in content:
        block = _as_object(item, "content block")
        if block.get("type") == "text":
            text = _as_text(block.get("text"), "content text")
            return _unwrapped(_as_object(json.loads(text), "content payload"))
    _abort("tools/call 응답에서 도구 결과를 찾지 못했습니다.")


def _unwrapped(payload: dict[str, object]) -> dict[str, object]:
    """Unwrap the single-key envelope the SDK adds to non-object returns."""
    if "ok" not in payload and set(payload) == {"result"}:
        return _as_object(payload["result"], "result payload")
    return payload


def _data(envelope: dict[str, object], label: str) -> object:
    """Return the payload of a successful envelope or abort with its error."""
    if envelope.get("ok") is not True:
        _abort(f"{label}: {json.dumps(envelope, ensure_ascii=False)}")
    return envelope.get("data")


def _error_code(envelope: dict[str, object]) -> str:
    error = envelope.get("error")
    if not isinstance(error, dict):
        return ""
    code = error.get("code")
    return code if isinstance(code, str) else ""


def _select_company(rows: list[object], query: str) -> dict[str, object]:
    companies = [_as_object(row, "company") for row in rows]
    for company in companies:
        if company.get("company_name") == query:
            return company
    if not companies:
        _abort(f"'{query}' 검색 결과가 비어 있습니다.")
    return companies[0]


def _select_filing(rows: list[object]) -> dict[str, object]:
    filings = [_as_object(row, "filing") for row in rows]
    if not filings:
        _abort("공시 목록이 비어 있습니다.")
    return max(filings, key=lambda filing: _as_text(filing.get("receipt_date"), "date"))


def _select_attachment(rows: list[object]) -> dict[str, object]:
    attachments = [_as_object(row, "attachment") for row in rows]
    separate = [
        attachment
        for attachment in attachments
        if attachment.get("standalone") is True
        and "감사보고서" in _as_text(attachment.get("title"), "title")
    ]
    if not separate:
        _abort("별도 감사보고서 첨부를 찾지 못했습니다.")
    return separate[0]


def _section_batches(summaries: list[dict[str, object]]) -> list[list[str]]:
    """Group section ids into requests that stay under the selection guard."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_cells = 0
    for summary in summaries:
        identifier = _as_text(summary.get("section_id"), "section_id")
        cells = _as_int(summary.get("cell_count"), "cell_count")
        if current and current_cells + cells > _BATCH_CELL_LIMIT:
            batches.append(current)
            current = []
            current_cells = 0
        current.append(identifier)
        current_cells += cells
    if current:
        batches.append(current)
    return batches


def _local_document(api_key: str, rcept_no: str, attachment_id: str) -> ParsedDocument:
    """Re-derive the same attachment through the public parsing API."""
    with HttpxClient() as http_client:
        service = AttachmentService(DartApi(http_client, api_key=api_key))
        listing = service.list(rcept_no)
        selection = _listed_attachment(listing, attachment_id)
        content = service.read_selected(rcept_no, selection)
        if not content.ok or content.data is None:
            _abort(f"로컬 첨부 읽기 실패: {content.error}")
        parsed = parse_attachment(content.data, attachment_id)
    if not parsed.ok or parsed.data is None:
        _abort(f"로컬 파싱 실패: {parsed.error}")
    return parsed.data


def _listed_attachment(
    listing: Result[tuple[Attachment, ...]],
    attachment_id: str,
) -> Attachment:
    if not listing.ok or listing.data is None:
        _abort(f"로컬 첨부 목록 실패: {listing.error}")
    for attachment in listing.data:
        if attachment.attachment_id == attachment_id:
            return attachment
    _abort(f"로컬 목록에 첨부 식별자가 없습니다: {attachment_id}")


def _compare_documents(
    document: ParsedDocument,
    remote_sections: list[dict[str, object]],
) -> tuple[list[str], int, int]:
    """Compare a local parse with the server's sections, cell by cell."""
    mismatches: list[str] = []
    if len(document.sections) != len(remote_sections):
        mismatches.append(
            f"섹션 수 불일치: 로컬 {len(document.sections)} vs 원격 {len(remote_sections)}"
        )
    compared_cells = 0
    compared_blocks = 0
    for index, local in enumerate(document.sections):
        if index >= len(remote_sections):
            break
        remote = remote_sections[index]
        mismatches.extend(_compare_section_identity(index, local, remote))
        local_blocks = local.blocks
        remote_blocks = [
            _as_object(block, "block")
            for block in _as_array(remote.get("blocks"), "blocks")
        ]
        if len(local_blocks) != len(remote_blocks):
            mismatches.append(
                f"[{index}] 블록 수 불일치: 로컬 {len(local_blocks)} vs 원격 {len(remote_blocks)}"
            )
        for position, local_block in enumerate(local_blocks):
            if position >= len(remote_blocks):
                break
            compared_blocks += 1
            compared_cells += _row_cells(local_block)
            mismatches.extend(
                _compare_block(index, position, local_block, remote_blocks[position])
            )
    return mismatches, compared_cells, compared_blocks


def _compare_section_identity(
    index: int,
    section: DocumentSection,
    remote: dict[str, object],
) -> list[str]:
    expected_id = section_id(index, section.kind)
    problems: list[str] = []
    if remote.get("section_id") != expected_id:
        problems.append(f"[{index}] section_id 불일치: {remote.get('section_id')!r} != {expected_id!r}")
    if remote.get("title") != section.title:
        problems.append(f"[{index}] 제목 불일치: {remote.get('title')!r} != {section.title!r}")
    if remote.get("kind") != section.kind.value:
        problems.append(f"[{index}] kind 불일치: {remote.get('kind')!r} != {section.kind.value!r}")
    return problems


def _compare_block(
    index: int,
    position: int,
    local: DocumentBlock,
    remote: dict[str, object],
) -> list[str]:
    label = f"[{index}:{position}]"
    problems: list[str] = []
    if remote.get("kind") != local.kind.value:
        problems.append(f"{label} 블록 kind 불일치: {remote.get('kind')!r} != {local.kind.value!r}")
    if remote.get("text", "") != local.text:
        problems.append(f"{label} 문단 텍스트 불일치")
    if remote.get("image_source") != local.image_source:
        problems.append(f"{label} 이미지 출처 불일치")
    table = remote.get("table")
    if local.kind is not BlockKind.TABLE:
        if table is not None:
            problems.append(f"{label} 표가 아닌 블록에 표 데이터가 있습니다.")
        return problems
    if not isinstance(table, dict):
        problems.append(f"{label} 표 블록에 표 데이터가 없습니다.")
        return problems
    problems.extend(_compare_table(label, local, _as_object(table, "table")))
    return problems


def _compare_table(
    label: str,
    local: DocumentBlock,
    table: dict[str, object],
) -> list[str]:
    problems: list[str] = []
    rows = tuple(
        tuple(_as_text(cell, "cell") for cell in _as_array(row, "row"))
        for row in _as_array(table.get("rows"), "rows")
    )
    if rows != local.rows:
        problems.append(f"{label} 표 셀 불일치: {_first_row_difference(local.rows, rows)}")
    merged = tuple(
        tuple(_as_int(value, "merge") for value in _as_array(item, "merged range"))
        for item in _as_array(table.get("merged_ranges", []), "merged_ranges")
    )
    if merged != local.merged_ranges:
        problems.append(f"{label} 병합 범위 불일치: 원격 {merged} != 로컬 {local.merged_ranges}")
    return problems


def _first_row_difference(
    local: tuple[tuple[str, ...], ...],
    remote: tuple[tuple[str, ...], ...],
) -> str:
    if len(local) != len(remote):
        return f"행 수 로컬 {len(local)} vs 원격 {len(remote)}"
    for row_number, (local_row, remote_row) in enumerate(zip(local, remote, strict=True), start=1):
        if local_row != remote_row:
            return f"{row_number}행 로컬 {local_row!r} vs 원격 {remote_row!r}"
    return "차이를 특정하지 못했습니다."


def _document_from_remote(sections: list[dict[str, object]]) -> ParsedDocument:
    """Rebuild a parsed document out of the JSON the server returned.

    Only the fields the workbook expectation builder reads are restored, so a
    match proves the response carries everything the Excel path consumes.
    """
    return ParsedDocument(
        sections=tuple(
            DocumentSection(
                title=_as_text(section.get("title"), "title"),
                kind=SectionKind(_as_text(section.get("kind"), "kind")),
                blocks=tuple(
                    _block_from_remote(_as_object(block, "block"))
                    for block in _as_array(section.get("blocks"), "blocks")
                ),
            )
            for section in sections
        ),
        source_sha256="",
        source_type="remote_json",
    )


def _block_from_remote(block: dict[str, object]) -> DocumentBlock:
    table = block.get("table")
    rows: tuple[tuple[str, ...], ...] = ()
    merged: tuple[tuple[int, int, int, int], ...] = ()
    if isinstance(table, dict):
        data = _as_object(table, "table")
        rows = tuple(
            tuple(_as_text(cell, "cell") for cell in _as_array(row, "row"))
            for row in _as_array(data.get("rows"), "rows")
        )
        merged = tuple(
            _merge_range(_as_array(item, "merged range"))
            for item in _as_array(data.get("merged_ranges", []), "merged_ranges")
        )
    image_source = block.get("image_source")
    return DocumentBlock(
        kind=BlockKind(_as_text(block.get("kind"), "kind")),
        text=_as_text(block.get("text", ""), "text"),
        rows=rows,
        image_source=image_source if isinstance(image_source, str) else None,
        merged_ranges=merged,
    )


def _merge_range(values: list[object]) -> tuple[int, int, int, int]:
    if len(values) != 4:
        _abort(f"병합 범위 원소가 4개가 아닙니다: {values!r}")
    start_row, start_column, end_row, end_column = (
        _as_int(value, "merge") for value in values
    )
    return (start_row, start_column, end_row, end_column)


def _expectation_mismatches(
    local: ParsedDocument,
    remote: ParsedDocument,
) -> tuple[list[str], int]:
    """Compare the workbook cell maps the two documents would produce."""
    local_sheets = _sheet_expectations(local)
    remote_sheets = _sheet_expectations(remote)
    problems: list[str] = []
    if len(local_sheets) != len(remote_sheets):
        problems.append(
            f"시트 수 불일치: 엑셀 경로 {len(local_sheets)} vs 데이터 경로 {len(remote_sheets)}"
        )
    compared = 0
    pairs = zip(local_sheets, remote_sheets, strict=False)
    for index, (expected, actual) in enumerate(pairs):
        compared += len(expected.cells)
        if expected.cells != actual.cells:
            problems.append(
                f"[{index}] 셀 맵 불일치: {_first_cell_difference(expected.cells, actual.cells)}"
            )
        if expected.merges != actual.merges:
            problems.append(
                f"[{index}] 병합 범위 불일치: {sorted(expected.merges ^ actual.merges)[:5]}"
            )
        if expected.number_formats != actual.number_formats:
            problems.append(f"[{index}] 표시형식 불일치")
    return problems, compared


def _first_cell_difference(
    expected: dict[CellCoordinate, CellValue],
    actual: dict[CellCoordinate, CellValue],
) -> str:
    for coordinate in sorted(set(expected) | set(actual)):
        if expected.get(coordinate) != actual.get(coordinate):
            return (
                f"{coordinate} 엑셀 {expected.get(coordinate)!r} "
                f"vs 데이터 {actual.get(coordinate)!r}"
            )
    return "차이를 특정하지 못했습니다."


def _row_cells(block: DocumentBlock) -> int:
    if block.kind is not BlockKind.TABLE:
        return 0
    return sum(len(row) for row in block.rows)


def _non_table_block_count(document: ParsedDocument) -> int:
    return sum(
        1
        for section in document.sections
        for block in section.blocks
        if block.kind is not BlockKind.TABLE
    )


def _balance_sheet_amounts(rows: list[object]) -> dict[str, str]:
    """Extract 재무상태표(BS) account amounts, keeping each account's first row.

    Shared by the direct-API fetch and the get_financial_statements tool
    response so the two are reduced identically before being compared.
    """
    amounts: dict[str, str] = {}
    for row in rows:
        account = _as_object(row, "account")
        if account.get("sj_div") != _BALANCE_SHEET_DIVISION:
            continue
        name = compact(_as_text(account.get("account_nm"), "account_nm"))
        amount = account.get("thstrm_amount")
        if isinstance(amount, str) and amount.strip():
            amounts.setdefault(name, amount)
    return amounts


def _official_balance_sheet(
    api_key: str,
    corp_code: str,
    business_year: int,
) -> dict[str, str]:
    """Fetch official balance-sheet amounts straight from OpenDART."""
    with httpx2.Client(timeout=httpx2.Timeout(connect=5.0, read=60.0, write=10.0, pool=10.0)) as client:
        response = client.get(
            _ACCOUNTS_URL,
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": str(business_year),
                "reprt_code": _ANNUAL_REPORT_CODE,
                "fs_div": _SEPARATE_SCOPE,
            },
        )
    payload = _as_object(response.json(), "fnlttSinglAcntAll 응답")
    status = payload.get("status")
    if status != "000":
        _abort(f"fnlttSinglAcntAll status={status!r} message={payload.get('message')!r}")
    return _balance_sheet_amounts(_as_array(payload.get("list"), "list"))


def _balance_sheet_rows(sections: list[dict[str, object]]) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for section in sections:
        if section.get("kind") != _BALANCE_SHEET_KIND:
            continue
        for block in _as_array(section.get("blocks"), "blocks"):
            table = _as_object(block, "block").get("table")
            if not isinstance(table, dict):
                continue
            rows.extend(
                tuple(_as_text(cell, "cell") for cell in _as_array(row, "row"))
                for row in _as_array(_as_object(table, "table").get("rows"), "rows")
            )
    return rows


def _numeric(text: str) -> Decimal | None:
    parsed = parse_cell_value(text)
    if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
        return None
    return Decimal(str(parsed))


def _match_official_amount(
    account: str,
    official: str,
    rows: list[tuple[str, ...]],
) -> dict[str, object]:
    """Find the statement cell that equals one official amount after scaling."""
    target = _numeric(official)
    for row in rows:
        if not row or compact(row[0]) != account:
            continue
        for column, cell in enumerate(row[1:], start=1):
            value = _numeric(cell)
            if value is None or target is None:
                continue
            for scale in _SCALE_FACTORS:
                if value * scale == target:
                    return {
                        "account": account,
                        "matched": True,
                        "official_amount": official,
                        "source_cell": cell,
                        "source_row": list(row),
                        "column_index": column,
                        "unit_scale": scale,
                    }
        return {
            "account": account,
            "matched": False,
            "official_amount": official,
            "source_row": list(row),
            "reason": "행은 찾았으나 어떤 배율로도 값이 일치하지 않았습니다.",
        }
    return {
        "account": account,
        "matched": False,
        "official_amount": official,
        "reason": "재무상태표에서 계정 행을 찾지 못했습니다.",
    }


def _run(client: RemoteClient, recorder: Recorder, api_key: str, query: str) -> None:
    """Drive the whole live flow, recording every check it decides."""
    tool_names = client.list_tools()
    recorder.facts["tool_names"] = list(tool_names)
    recorder.record(
        "tools/list surface",
        passed=len(tool_names) == 12 and "export_report_excel" not in tool_names,
        detail=f"{len(tool_names)}개: {', '.join(tool_names)}",
    )

    company = _select_company(
        _as_array(
            _data(client.call("search_companies", {"company_query": query, "report_kind": "audit"}), "search_companies"),
            "companies",
        ),
        query,
    )
    corp_code = _as_text(company.get("corp_code"), "corp_code")
    recorder.facts["company"] = company
    recorder.record(
        "search_companies",
        passed=True,
        detail=f"{company.get('company_name')} corp_code={corp_code} match={company.get('match_confidence')}",
    )

    filing = _select_filing(
        _as_array(
            _data(client.call("list_report_filings", {"corp_code": corp_code, "report_kind": "audit"}), "list_report_filings"),
            "filings",
        )
    )
    rcept_no = _as_text(filing.get("rcept_no"), "rcept_no")
    business_year = _as_int(filing.get("fiscal_year"), "fiscal_year")
    recorder.facts["filing"] = filing
    recorder.record(
        "list_report_filings",
        passed=True,
        detail=f"{filing.get('report_name')} rcept_no={rcept_no} receipt_date={filing.get('receipt_date')}",
    )

    attachment = _select_attachment(
        _as_array(
            _data(client.call("list_report_attachments", {"rcept_no": rcept_no}), "list_report_attachments"),
            "attachments",
        )
    )
    attachment_id = _as_text(attachment.get("attachment_id"), "attachment_id")
    recorder.facts["attachment"] = attachment
    recorder.record(
        "list_report_attachments",
        passed=True,
        detail=f"{attachment.get('title')} attachment_id={attachment_id}",
    )

    toc = _as_object(
        _data(client.call("list_report_sections", {"rcept_no": rcept_no, "attachment_id": attachment_id}), "list_report_sections"),
        "ReportSectionList",
    )
    summaries = [_as_object(row, "summary") for row in _as_array(toc.get("sections"), "sections")]
    recorder.facts["toc"] = {
        "report_title": toc.get("report_title"),
        "source_type": toc.get("source_type"),
        "source_sha256": toc.get("source_sha256"),
        "coverage_complete": toc.get("coverage_complete"),
        "section_count": toc.get("section_count"),
        "total_cell_count": toc.get("total_cell_count"),
        "total_text_char_count": toc.get("total_text_char_count"),
        "first_sections": [
            {key: summary.get(key) for key in ("section_id", "title", "kind", "cell_count", "text_char_count")}
            for summary in summaries[:12]
        ],
    }
    recorder.record(
        "list_report_sections",
        passed=len(summaries) == _as_int(toc.get("section_count"), "section_count"),
        detail=f"섹션 {toc.get('section_count')}개, 표 셀 {toc.get('total_cell_count')}개, 서술 {toc.get('total_text_char_count')}자, coverage_complete={toc.get('coverage_complete')}",
    )

    statements = _as_object(
        _data(
            client.call(
                "get_report_sections",
                {"rcept_no": rcept_no, "attachment_id": attachment_id, "section_kinds": [_STATEMENTS_ALIAS]},
                label="get_report_sections(statements)",
            ),
            "get_report_sections(statements)",
        ),
        "ReportSectionData",
    )
    statement_sections = [_as_object(row, "section") for row in _as_array(statements.get("sections"), "sections")]
    recorder.facts["statements"] = {
        "returned_cell_count": statements.get("returned_cell_count"),
        "sections": [
            {key: section.get(key) for key in ("section_id", "title", "kind")}
            for section in statement_sections
        ],
        "balance_sheet_sample_rows": _balance_sheet_rows(statement_sections)[:8],
    }
    recorder.record(
        "get_report_sections(statements)",
        passed=bool(statement_sections),
        detail=f"{len(statement_sections)}개 구역, 셀 {statements.get('returned_cell_count')}개: "
        + ", ".join(_as_text(section.get("title"), "title") for section in statement_sections),
    )

    note_summary = next(
        (summary for summary in summaries if summary.get("kind") == _NOTE_KIND),
        None,
    )
    if note_summary is not None:
        note_id = _as_text(note_summary.get("section_id"), "section_id")
        note = _as_object(
            _data(
                client.call(
                    "get_report_sections",
                    {"rcept_no": rcept_no, "attachment_id": attachment_id, "section_ids": [note_id]},
                    label="get_report_sections(note)",
                ),
                "get_report_sections(note)",
            ),
            "ReportSectionData",
        )
        note_sections = [_as_object(row, "section") for row in _as_array(note.get("sections"), "sections")]
        first_note = note_sections[0] if note_sections else {}
        recorder.facts["note_section"] = {
            "section_id": first_note.get("section_id"),
            "title": first_note.get("title"),
            "block_count": len(_as_array(first_note.get("blocks", []), "blocks")),
            "returned_cell_count": note.get("returned_cell_count"),
        }
        recorder.record(
            "get_report_sections(note by section_id)",
            passed=len(note_sections) == 1 and first_note.get("section_id") == note_id,
            detail=f"{first_note.get('section_id')} {first_note.get('title')!r} 셀 {note.get('returned_cell_count')}개",
        )

    _run_negative_cases(client, recorder, rcept_no, query)
    remote_sections, returned_total = _collect_all_sections(client, recorder, summaries, rcept_no, attachment_id)
    _run_cross_check(recorder, api_key, rcept_no, attachment_id, remote_sections, returned_total)
    _run_official_check(recorder, api_key, corp_code, business_year, statement_sections)
    _run_financial_data_tools_check(client, recorder, api_key, corp_code, business_year)
    _run_report_topics_check(client, recorder, corp_code, business_year)
    _run_company_profile_check(client, recorder, corp_code)
    _run_ownership_reports_check(client, recorder, corp_code)
    _run_material_events_check(client, recorder, corp_code)


def _run_negative_cases(
    client: RemoteClient,
    recorder: Recorder,
    rcept_no: str,
    query: str,
) -> None:
    """Check the missing-key envelope and the Authorization: Bearer fallback."""
    without_key = client.call(
        "list_report_attachments",
        {"rcept_no": rcept_no},
        auth="none",
        label="list_report_attachments(키 없음)",
    )
    recorder.facts["missing_key_envelope"] = without_key
    recorder.record(
        "키 헤더 없음 → CONFIG_ERROR",
        passed=without_key.get("ok") is False and _error_code(without_key) == "CONFIG_ERROR",
        detail=f"ok={without_key.get('ok')} code={_error_code(without_key)!r}",
    )
    bearer = client.call(
        "search_companies",
        {"company_query": query, "report_kind": "audit"},
        auth="bearer",
        label="search_companies(Bearer)",
    )
    recorder.facts["bearer_ok"] = bearer.get("ok")
    recorder.record(
        "Authorization: Bearer 폴백",
        passed=bearer.get("ok") is True and _error_code(bearer) != "CONFIG_ERROR",
        detail=f"ok={bearer.get('ok')} code={_error_code(bearer)!r}",
    )


def _collect_all_sections(
    client: RemoteClient,
    recorder: Recorder,
    summaries: list[dict[str, object]],
    rcept_no: str,
    attachment_id: str,
) -> tuple[list[dict[str, object]], int]:
    """Request every section in guard-sized batches, in source order."""
    batches = _section_batches(summaries)
    collected: list[dict[str, object]] = []
    returned_total = 0
    for number, batch in enumerate(batches, start=1):
        payload = _as_object(
            _data(
                client.call(
                    "get_report_sections",
                    {"rcept_no": rcept_no, "attachment_id": attachment_id, "section_ids": batch},
                    label=f"get_report_sections(batch {number}/{len(batches)})",
                ),
                f"get_report_sections(batch {number})",
            ),
            "ReportSectionData",
        )
        returned_total += _as_int(payload.get("returned_cell_count"), "returned_cell_count")
        collected.extend(
            _as_object(row, "section") for row in _as_array(payload.get("sections"), "sections")
        )
    recorder.record(
        "전 구역 수집",
        passed=len(collected) == len(summaries),
        detail=f"{len(batches)}회 호출로 {len(collected)}/{len(summaries)}개 구역, 표 셀 {returned_total}개",
    )
    return collected, returned_total


def _run_cross_check(
    recorder: Recorder,
    api_key: str,
    rcept_no: str,
    attachment_id: str,
    remote_sections: list[dict[str, object]],
    returned_total: int,
) -> None:
    """Compare an independent local parse with everything the server returned."""
    started = time.perf_counter()
    document = _local_document(api_key, rcept_no, attachment_id)
    recorder.time("독립 로컬 파싱", time.perf_counter() - started)
    mismatches, compared_cells, compared_blocks = _compare_documents(document, remote_sections)
    recorder.facts["cross_check"] = {
        "local_source_sha256": document.source_sha256,
        "sections_compared": len(document.sections),
        "blocks_compared": compared_blocks,
        "table_cells_compared": compared_cells,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:10],
    }
    recorder.record(
        "셀 단위 교차 검증 (zero-missing)",
        passed=not mismatches,
        detail=f"구역 {len(document.sections)}개, 블록 {compared_blocks}개, 표 셀 {compared_cells}개 비교, 불일치 {len(mismatches)}건",
    )
    expectation_problems, expectation_cells = _expectation_mismatches(
        document,
        _document_from_remote(remote_sections),
    )
    recorder.facts["sheet_expectations"] = {
        "sheets_compared": len(document.sections),
        "expectation_cells_compared": expectation_cells,
        "mismatch_count": len(expectation_problems),
        "mismatches": expectation_problems[:10],
    }
    recorder.record(
        "엑셀 경로 셀 맵 대조 (_sheet_expectations)",
        passed=not expectation_problems,
        detail=f"시트 {len(document.sections)}개, 좌표-값 {expectation_cells}개 비교, 불일치 {len(expectation_problems)}건",
    )
    validation = validate_document(document)
    if not validation.ok or validation.data is None:
        recorder.record("대사 항등식", passed=False, detail=f"validate_document 실패: {validation.error}")
        return
    non_table = _non_table_block_count(document)
    checked = validation.data.checked_cell_count
    recorder.facts["reconciliation"] = {
        "checked_cell_count": checked,
        "returned_cell_count_total": returned_total,
        "non_table_block_count": non_table,
    }
    recorder.record(
        "대사 항등식 checked == returned + 비표 블록",
        passed=checked == returned_total + non_table,
        detail=f"{checked} == {returned_total} + {non_table} ({returned_total + non_table})",
    )


def _run_official_check(
    recorder: Recorder,
    api_key: str,
    corp_code: str,
    business_year: int,
    statement_sections: list[dict[str, object]],
) -> None:
    """Match statement cells against OpenDART's official account amounts."""
    official = _official_balance_sheet(api_key, corp_code, business_year)
    rows = _balance_sheet_rows(statement_sections)
    matches = [
        _match_official_amount(account, official[account], rows)
        for account in _OFFICIAL_ACCOUNT_NAMES
        if account in official
    ]
    matched = [match for match in matches if match.get("matched") is True]
    recorder.facts["official_figures"] = {
        "business_year": business_year,
        "fs_div": _SEPARATE_SCOPE,
        "reprt_code": _ANNUAL_REPORT_CODE,
        "matches": matches,
    }
    recorder.record(
        "공식 금액 대조 (3건 이상)",
        passed=len(matched) >= 3,
        detail="; ".join(
            f"{match['account']} 원문 {match.get('source_cell')!r} x{match.get('unit_scale')} == 공식 {match['official_amount']}"
            if match.get("matched")
            else f"{match['account']} 불일치({match.get('reason')})"
            for match in matches
        )
        or "재무상태표 계정을 하나도 대조하지 못했습니다.",
    )


def _run_financial_data_tools_check(
    client: RemoteClient,
    recorder: Recorder,
    api_key: str,
    corp_code: str,
    business_year: int,
) -> None:
    """Cross-check get_financial_statements and smoke-test get_financial_indicators.

    get_financial_statements and the direct fnlttSinglAcntAll call hit the
    same OpenDART endpoint, so their balance-sheet amounts must match
    exactly rather than merely after unit scaling.
    """
    official = _official_balance_sheet(api_key, corp_code, business_year)
    statements = _as_object(
        _data(
            client.call(
                "get_financial_statements",
                {
                    "corp_code": corp_code,
                    "bsns_year": business_year,
                    "reprt_code": _ANNUAL_REPORT_CODE,
                    "fs_div": _SEPARATE_SCOPE,
                },
                label="get_financial_statements",
            ),
            "get_financial_statements",
        ),
        "FinancialStatementData",
    )
    tool_amounts = _balance_sheet_amounts(_as_array(statements.get("accounts"), "accounts"))
    comparisons = [
        (account, tool_amounts.get(account), official[account])
        for account in _OFFICIAL_ACCOUNT_NAMES
        if account in official
    ]
    mismatches = [
        f"{account} 도구={tool_amount!r} 직접호출={official_amount!r}"
        for account, tool_amount, official_amount in comparisons
        if tool_amount != official_amount
    ]
    recorder.facts["get_financial_statements"] = {
        "returned_row_count": statements.get("returned_row_count"),
        "compared_accounts": [account for account, _tool, _official in comparisons],
        "mismatches": mismatches,
    }
    recorder.record(
        "get_financial_statements == fnlttSinglAcntAll 직접호출 (자산총계/부채총계/자본총계)",
        passed=bool(comparisons) and not mismatches,
        detail="; ".join(f"{account}={amount}" for account, amount, _official in comparisons)
        or "비교할 재무상태표 계정을 찾지 못했습니다.",
    )

    indicators = _as_object(
        _data(
            client.call(
                "get_financial_indicators",
                {
                    "corp_codes": [corp_code],
                    "bsns_year": business_year,
                    "reprt_code": _ANNUAL_REPORT_CODE,
                    "idx_cl_code": "M210000",
                },
                label="get_financial_indicators",
            ),
            "get_financial_indicators",
        ),
        "FinancialIndicatorData",
    )
    indicator_rows = _as_array(indicators.get("indicators"), "indicators")
    recorder.facts["get_financial_indicators"] = {
        "returned_row_count": indicators.get("returned_row_count"),
        "row_count_observed": len(indicator_rows),
    }
    # Row presence legitimately varies by company/year, so only the envelope
    # parsing is asserted here (an ok=False response would already have
    # aborted inside _data above); the row count is recorded, not required.
    recorder.record(
        "get_financial_indicators 응답 봉투 파싱",
        passed=True,
        detail=f"idx_cl_code=M210000 행 {len(indicator_rows)}개",
    )


def _run_report_topics_check(
    client: RemoteClient,
    recorder: Recorder,
    corp_code: str,
    business_year: int,
) -> None:
    """Smoke-test get_report_topics(audit_opinion) for the default company.

    Row presence legitimately varies by company/year even for a topic that
    reliably carries data, so row_count is recorded rather than required:
    an empty result degrades to a printed note instead of aborting the run.
    """
    topics = _as_array(
        _as_object(
            _data(
                client.call(
                    "get_report_topics",
                    {
                        "corp_code": corp_code,
                        "bsns_year": business_year,
                        "reprt_code": _ANNUAL_REPORT_CODE,
                        "topics": ["audit_opinion"],
                    },
                    label="get_report_topics(audit_opinion)",
                ),
                "get_report_topics(audit_opinion)",
            ),
            "ReportTopicData",
        ).get("topics"),
        "topics",
    )
    topic_rows = [_as_object(row, "topic") for row in topics]
    audit_opinion = next(
        (row for row in topic_rows if row.get("topic") == "audit_opinion"),
        None,
    )
    label = audit_opinion.get("label") if audit_opinion is not None else None
    row_count = (
        _as_int(audit_opinion.get("row_count"), "row_count")
        if audit_opinion is not None
        else 0
    )
    recorder.facts["get_report_topics"] = {
        "topics": [
            {key: row.get(key) for key in ("topic", "label", "row_count")}
            for row in topic_rows
        ],
    }
    recorder.record(
        "get_report_topics(audit_opinion) 라벨링",
        passed=audit_opinion is not None and isinstance(label, str) and bool(label),
        detail=f"topic=audit_opinion label={label!r}",
    )
    # Row presence legitimately varies by company/year, so only the envelope
    # and labeling are asserted above; the row count is recorded, not
    # required (see the get_financial_indicators check for the same pattern).
    recorder.record(
        "get_report_topics(audit_opinion) row_count",
        passed=True,
        detail=f"row_count={row_count}",
    )
    if row_count < 1:
        print(
            "[WARN] get_report_topics(audit_opinion) row_count=0 for "
            f"corp_code={corp_code} bsns_year={business_year} — "
            "사업보고서 감사의견 데이터가 비어 있습니다."
        )


def _run_company_profile_check(
    client: RemoteClient,
    recorder: Recorder,
    corp_code: str,
) -> None:
    """Smoke-test get_company_profile for the script's default company.

    corp_name is asserted non-empty (a hard requirement for any real
    company); every other field is recorded rather than required, since
    company.json legitimately leaves optional fields blank for some issuers.
    """
    profile = _as_object(
        _data(
            client.call(
                "get_company_profile",
                {"corp_code": corp_code},
                label="get_company_profile",
            ),
            "get_company_profile",
        ),
        "CompanyProfileData",
    )
    recorder.facts["get_company_profile"] = {
        key: profile.get(key)
        for key in (
            "corp_code",
            "corp_name",
            "corp_name_eng",
            "stock_name",
            "stock_code",
            "ceo_nm",
            "corp_cls",
            "est_dt",
            "acc_mt",
        )
    }
    corp_name = profile.get("corp_name")
    recorder.record(
        "get_company_profile corp_name",
        passed=isinstance(corp_name, str) and bool(corp_name),
        detail=f"corp_code={corp_code} corp_name={corp_name!r}",
    )


def _run_ownership_reports_check(
    client: RemoteClient,
    recorder: Recorder,
    corp_code: str,
) -> None:
    """Smoke-test get_ownership_reports(major_holding) for the default company.

    Row presence legitimately varies by company, so row_count is recorded
    rather than required (see the get_financial_indicators and
    get_report_topics checks for the same pattern); only the envelope shape
    is asserted.
    """
    report = _as_object(
        _data(
            client.call(
                "get_ownership_reports",
                {"corp_code": corp_code, "report_type": "major_holding"},
                label="get_ownership_reports(major_holding)",
            ),
            "get_ownership_reports(major_holding)",
        ),
        "OwnershipReportData",
    )
    row_count = _as_int(report.get("returned_row_count"), "returned_row_count")
    recorder.facts["get_ownership_reports"] = {
        "report_type": report.get("report_type"),
        "label": report.get("label"),
        "returned_row_count": row_count,
    }
    recorder.record(
        "get_ownership_reports(major_holding) 응답 봉투 파싱",
        passed=report.get("report_type") == "major_holding"
        and isinstance(report.get("label"), str)
        and bool(report.get("label")),
        detail=f"report_type=major_holding label={report.get('label')!r} row_count={row_count}",
    )
    if row_count < 1:
        print(
            "[WARN] get_ownership_reports(major_holding) row_count=0 for "
            f"corp_code={corp_code} — 대량보유 상황보고 데이터가 비어 있습니다."
        )


def _run_material_events_check(
    client: RemoteClient,
    recorder: Recorder,
    corp_code: str,
) -> None:
    """Smoke-test get_material_events for the script's default company.

    Row presence legitimately varies by company and period — and a company
    genuinely having filed neither event type in range is itself a valid
    answer under this tool's all-empty-still-succeeds policy — so row counts
    are recorded rather than required (see the get_financial_indicators and
    get_report_topics checks for the same pattern); only the envelope shape
    and event_type/label echo are asserted as hard checks.
    """
    bgn_de = "20200101"
    end_de = time.strftime("%Y%m%d")
    event_types = ["treasury_stock_acquisition", "merger"]
    payload = _as_object(
        _data(
            client.call(
                "get_material_events",
                {
                    "corp_code": corp_code,
                    "event_types": event_types,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
                label="get_material_events",
            ),
            "get_material_events",
        ),
        "MaterialEventData",
    )
    events = [
        _as_object(row, "event") for row in _as_array(payload.get("events"), "events")
    ]
    row_counts = {
        _as_text(event.get("event_type"), "event_type"): _as_int(
            event.get("row_count"), "row_count"
        )
        for event in events
    }
    labels = {
        _as_text(event.get("event_type"), "event_type"): event.get("label")
        for event in events
    }
    recorder.facts["get_material_events"] = {
        "bgn_de": bgn_de,
        "end_de": end_de,
        "event_types": event_types,
        "row_counts": row_counts,
        "labels": labels,
        "returned_row_count": payload.get("returned_row_count"),
    }
    recorder.record(
        "get_material_events 응답 봉투 및 라벨링",
        passed=set(row_counts) == set(event_types)
        and all(isinstance(label, str) and bool(label) for label in labels.values()),
        detail=f"event_types={event_types} row_counts={row_counts}",
    )
    if all(count == 0 for count in row_counts.values()):
        print(
            "[WARN] get_material_events row_count=0 for every requested "
            f"event_type, corp_code={corp_code} bgn_de={bgn_de} end_de={end_de} — "
            "해당 기간에 주요사항보고 정보가 비어 있습니다."
        )


def main(argv: list[str] | None = None) -> int:
    """Run the live validation and return a process exit code."""
    stream = sys.stdout
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="원격 MCP 데이터 서비스 라이브 검증")
    parser.add_argument("url", nargs="?", default=_DEFAULT_URL, help="MCP 엔드포인트 주소")
    parser.add_argument("--company", default="삼성전자", help="검색할 회사명")
    args = parser.parse_args(argv)
    api_key = os.environ.get(_ENV_KEY_NAME, "").strip()
    if not api_key:
        print(f"{_ENV_KEY_NAME} 환경변수가 비어 있습니다.")
        return 2
    recorder = Recorder()
    recorder.facts["server_url"] = args.url
    recorder.facts["api_key_header"] = f"{_KEY_HEADER}: ****"
    print(f"대상 서버 {args.url} / 헤더 {_KEY_HEADER}: ****")
    failure: str | None = None
    try:
        with RemoteClient(args.url, api_key, recorder) as client:
            _run(client, recorder, api_key, args.company)
    except LiveValidationError as error:
        failure = str(error)
        recorder.record("실행 완료", passed=False, detail=failure)
    except httpx2.HTTPError as error:
        failure = f"HTTP 오류: {error}"
        recorder.record("실행 완료", passed=False, detail=failure)
    summary: dict[str, object] = {
        "passed": recorder.passed,
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in recorder.checks
        ],
        "timings_seconds": recorder.timings,
        "facts": recorder.facts,
    }
    if failure is not None:
        summary["aborted_with"] = failure
    print("--- SUMMARY JSON ---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"--- {'PASS' if recorder.passed else 'FAIL'}: {sum(1 for c in recorder.checks if c.passed)}/{len(recorder.checks)} 검사 통과 ---")
    return 0 if recorder.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
