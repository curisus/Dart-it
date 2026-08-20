from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from pydantic import SecretStr

from dart_crawler import markdown_export
from dart_crawler.api_models import DartListRow
from dart_crawler.crawler_service import CrawlerService
from dart_crawler.dart_api import DartApi
from dart_crawler.document_model import (
    BlockKind,
    DocumentSection,
    ParsedDocument,
    SectionKind,
)
from dart_crawler.excel_export import ExportContext
from dart_crawler.http_client import HttpResponse
from dart_crawler.markdown_export import MarkdownExportService
from dart_crawler.result import ErrorCode, Result, WarningCode
from dart_crawler.xml_parser import parse_xml_document

_RCEPT_NO = "20260310002820"
_ATTACHMENT_ID = "opendart:20260310002820:audit.xml"


def _parse_document(markup: str) -> ParsedDocument:
    result = parse_xml_document(markup.encode())
    assert result.ok is True
    assert result.data is not None
    return result.data


def _document() -> ParsedDocument:
    return _parse_document(
        "<document>"
        "<heading>재무상태표</heading>"
        "<table><tr><td>자산</td><td>1,000</td></tr></table>"
        "<heading>손익 및 포괄손익계산서</heading>"
        "<table><tr><td>매출</td><td>(10)</td></tr></table>"
        "<heading>자본변동표</heading>"
        "<table><tr><td>자본</td><td>5</td></tr></table>"
        "<heading>현금흐름표</heading>"
        "<table><tr><td>현금</td><td>6</td></tr></table>"
        "<heading>주석 1</heading>"
        "<p>주요 회계정책에 대한 설명입니다.</p>"
        "</document>"
    )


def _context(document: ParsedDocument) -> ExportContext:
    return ExportContext(
        company_name="Sample Company",
        report_date="2026-03-10",
        report_title="감사보고서",
        receipt_date="20260310",
        rcept_no=_RCEPT_NO,
        source_rcept_no=_RCEPT_NO,
        attachment_id=_ATTACHMENT_ID,
        correction_chain=(_RCEPT_NO,),
        source_url="https://dart.example/report",
        parser_version="0.1.0",
        document=document,
    )


def test_export_renders_every_section_with_tables_and_text(tmp_path: Path) -> None:
    # Given
    document = _document()

    # When
    result = MarkdownExportService(tmp_path).export(_context(document))

    # Then
    assert result.ok is True
    assert result.data is not None
    data = result.data
    assert data.collection_status.value == "complete"
    assert data.missing_sections == ()
    assert data.reused is False
    assert data.output_path.exists()
    assert data.output_path.suffix == ".md"
    content = data.output_path.read_text(encoding="utf-8")
    assert "# Sample Company 감사보고서 (2026-03-10)" in content
    assert "## 재무상태표 (balance_sheet)" in content
    assert "| 자산 | 1,000 |" in content
    assert "| --- | --- |" in content
    assert "## 주석 1 (note)" in content
    assert "주요 회계정책에 대한 설명입니다." in content
    table_count = sum(
        1
        for section in document.sections
        for block in section.blocks
        if block.kind is BlockKind.TABLE
    )
    assert data.rendered_section_count == len(document.sections)
    assert data.rendered_table_count == table_count
    # The count must describe the real artifact, not a formula the
    # implementation shares: compare against the written file itself.
    assert data.rendered_char_count == len(content)
    assert result.warnings == ()


def test_export_reuses_existing_file_without_duplicating(tmp_path: Path) -> None:
    # Given
    context = _context(_document())
    service = MarkdownExportService(tmp_path)

    # When
    first = service.export(context)
    assert first.ok is True
    assert first.data is not None
    first_content = first.data.output_path.read_text(encoding="utf-8")
    first_mtime_ns = first.data.output_path.stat().st_mtime_ns
    second = service.export(context)

    # Then
    assert first.ok is True
    assert first.data is not None
    assert first.data.reused is False
    assert second.ok is True
    assert second.data is not None
    assert second.data.reused is True
    assert second.data.output_path == first.data.output_path
    assert len(list(tmp_path.glob("*.md"))) == 1
    # Reuse must not rewrite the file: same bytes, same mtime.
    assert first.data.output_path.read_text(encoding="utf-8") == first_content
    assert first.data.output_path.stat().st_mtime_ns == first_mtime_ns
    assert any(
        warning.code is WarningCode.EXISTING_FILE_REUSED for warning in second.warnings
    )


def test_export_succeeds_with_partial_collection_when_core_statement_missing(
    tmp_path: Path,
) -> None:
    # Given
    document = _parse_document(
        "<document><heading>주석 1</heading>"
        "<table><tr><td>내용</td><td>값</td></tr></table></document>"
    )

    # When
    result = MarkdownExportService(tmp_path).export(_context(document))

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.collection_status.value == "partial"
    assert result.data.missing_sections == (
        "재무상태표",
        "손익·포괄손익",
        "자본변동표",
        "현금흐름표",
    )
    assert result.data.output_path.exists()
    warning = next(
        warning
        for warning in result.warnings
        if warning.code is WarningCode.PARTIAL_COLLECTION
    )
    assert warning.details["missing_sections"] == [
        "재무상태표",
        "손익·포괄손익",
        "자본변동표",
        "현금흐름표",
    ]


def test_export_rejects_document_that_fails_validation(tmp_path: Path) -> None:
    # Given
    document = replace(_document(), source_coverage=None)

    # When
    result = MarkdownExportService(tmp_path).export(_context(document))

    # Then
    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "VALIDATION_FAILED"
    assert list(tmp_path.glob("*.md")) == []


def test_render_table_pads_short_rows_and_emits_header_separator() -> None:
    # When
    rendered = markdown_export._render_table(
        (("계정", "당기", "전기"), ("자산총계",))
    )

    # Then
    assert rendered[0] == "| 계정 | 당기 | 전기 |"
    assert rendered[1] == "| --- | --- | --- |"
    header_columns = rendered[0].strip("|").split("|")
    padded_columns = rendered[2].strip("|").split("|")
    assert len(padded_columns) == len(header_columns) == 3
    assert padded_columns[0].strip() == "자산총계"
    assert padded_columns[1].strip() == ""
    assert padded_columns[2].strip() == ""


def test_escape_cell_escapes_pipe_and_converts_newline() -> None:
    assert markdown_export._escape_cell("a|b") == "a\\|b"
    assert markdown_export._escape_cell("line1\nline2") == "line1<br>line2"
    assert markdown_export._escape_cell("line1\r\nline2") == "line1<br>line2"


def test_render_section_renders_placeholder_for_empty_section() -> None:
    # Given
    section = DocumentSection(title="빈 구역", kind=SectionKind.OTHER, blocks=())

    # When
    rendered = markdown_export._render_section(section)

    # Then
    assert rendered == ["## 빈 구역 (other)", "", "_내용 없음_", ""]


@dataclass(slots=True)
class _RecordingHttpClient:
    """Fake HTTP client that records every attempted request."""

    requested_urls: list[str] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        self.requested_urls.append(url)
        return HttpResponse(status_code=200, headers={}, content=b"")

    def close(self) -> None:
        return None


def _forbid_disclosure(_self: DartApi, rcept_no: str) -> Result[DartListRow]:
    raise AssertionError(rcept_no)


def test_crawler_service_export_report_markdown_without_output_dir_fails_with_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(DartApi, "find_disclosure", _forbid_disclosure)
    http_client = _RecordingHttpClient()
    service = CrawlerService(SecretStr("test-key"), http_client)

    # When
    result = service.export_report_markdown(_RCEPT_NO, _ATTACHMENT_ID)

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.CONFIG_ERROR
    assert result.error.retryable is False
    assert result.next_action is not None
    assert http_client.requested_urls == []


def test_export_survives_existing_non_utf8_file_at_output_path(
    tmp_path: Path,
) -> None:
    # Given: a stale non-UTF-8 file already sits at the deterministic path
    # (regression: the reuse probe crashed with UnicodeDecodeError instead
    # of treating the unreadable file as a mismatch)
    context = _context(_document())
    service = MarkdownExportService(tmp_path)
    first = service.export(context)
    assert first.ok is True
    assert first.data is not None
    first.data.output_path.write_bytes(b"\xff\xfe not utf-8")

    # When
    result = service.export(context)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data.reused is False
    assert result.data.output_path != first.data.output_path
