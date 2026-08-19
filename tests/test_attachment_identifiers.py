from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import assert_never
from zipfile import ZipFile

import pytest
from pydantic import SecretStr

from dart_crawler.api_models import DartListRow, FinancialAccount
from dart_crawler.attachments import AttachmentService, _attachment_name
from dart_crawler.crawler_service import CrawlerService
from dart_crawler.dart_api import DartApi, FinancialQuery
from dart_crawler.domain import Attachment
from dart_crawler.excel_export import (
    CollectionStatus,
    ExcelExportService,
    ExportContext,
    ExportedFile,
    ValidationStatus,
)
from dart_crawler.http_client import HttpResponse
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.settings import AppSettings
from dart_crawler.zip_safety import ArchiveLimits, inspect_archive

_DEFAULT_MEMBER_CONTENT = "<document><title>감사보고서</title></document>"


def _archive(
    member_content: str = _DEFAULT_MEMBER_CONTENT,
    member_name: str = "audit.xml",
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(member_name, member_content)
    return buffer.getvalue()


@dataclass(slots=True)
class RecordingAttachmentSource:
    """Mutable fake that records downloaded receipt numbers."""

    archives: dict[str, bytes]
    viewer_html: bytes = b""
    download_calls: list[str] = field(default_factory=list)

    def download_document(self, rcept_no: str) -> Result[bytes]:
        self.download_calls.append(rcept_no)
        archive = self.archives.get(rcept_no)
        if archive is None:
            return Result[bytes].failure(
                error_info(
                    ErrorCode.NOT_FOUND,
                    "첨부 원문을 찾지 못했습니다.",
                    retryable=False,
                )
            )
        return Result[bytes].success(archive)

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        assert rcept_no
        return Result[bytes].success(self.viewer_html)

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        assert rcept_no
        assert dcm_no
        return Result[bytes].success(b"")


@dataclass(frozen=True, slots=True)
class NoopHttpClient:
    def get(self, url: str, *, params: dict[str, str]) -> HttpResponse:
        raise AssertionError((url, params))

    def close(self) -> None:
        return None


def _crawler_service(output_dir: Path) -> CrawlerService:
    return CrawlerService(
        AppSettings(
            project_dir=output_dir,
            api_key=SecretStr("test-key"),
            output_dir=output_dir,
        ),
        NoopHttpClient(),
    )


def _disclosure(rcept_no: str) -> DartListRow:
    return DartListRow(
        corp_name="테스트회사",
        corp_code="00126380",
        report_nm="2025년 감사보고서",
        rcept_no=rcept_no,
        rcept_dt="20260515",
    )


def _configure_export(
    monkeypatch: pytest.MonkeyPatch,
    output_dir: Path,
    listing: Result[tuple[Attachment, ...]],
) -> tuple[CrawlerService, ExportedFile, list[str], list[ExportContext]]:
    requested_rcept_no = "20260515001658"
    read_ids: list[str] = []
    contexts: list[ExportContext] = []
    exported = ExportedFile(
        output_path=output_dir / "report.xlsx",
        collection_status=CollectionStatus.COMPLETE,
        reused=False,
        missing_sections=(),
        source_sha256="source-hash",
        validation_status=ValidationStatus.PASSED,
        validated_cell_count=1,
        validated_merge_count=0,
    )

    def find_disclosure(_self: DartApi, rcept_no: str) -> Result[DartListRow]:
        return Result.success(_disclosure(rcept_no))

    def list_attachments(
        _self: AttachmentService,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        assert rcept_no == requested_rcept_no
        return listing

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        assert rcept_no == requested_rcept_no
        match selection:
            case Attachment() as attachment:
                read_ids.append(attachment.attachment_id)
            case str() as attachment_id:
                read_ids.append(attachment_id)
            case unreachable:
                assert_never(unreachable)
        return Result.success(_DEFAULT_MEMBER_CONTENT.encode())

    def fetch_financial_accounts(
        _self: DartApi,
        query: FinancialQuery,
    ) -> Result[tuple[FinancialAccount, ...]]:
        assert query.corp_code == "00126380"
        return Result.success(())

    def list_disclosures(
        _self: DartApi,
        corp_code: str,
        report_detail_type: str,
    ) -> Result[tuple[DartListRow, ...]]:
        assert corp_code == "00126380"
        assert report_detail_type == "A001"
        return Result.success(())

    def export(
        _self: ExcelExportService,
        context: ExportContext,
    ) -> Result[ExportedFile]:
        contexts.append(context)
        return Result.success(exported)

    monkeypatch.setattr(DartApi, "find_disclosure", find_disclosure)
    monkeypatch.setattr(AttachmentService, "list", list_attachments)
    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)
    monkeypatch.setattr(DartApi, "fetch_financial_accounts", fetch_financial_accounts)
    monkeypatch.setattr(DartApi, "list_disclosures", list_disclosures)
    monkeypatch.setattr(ExcelExportService, "export", export)
    return _crawler_service(output_dir), exported, read_ids, contexts


def test_extended_attachment_name_is_rejected_as_zip_member() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    source_rcept_no = "20260312001119"
    extended_name = _attachment_name(
        requested_rcept_no,
        source_rcept_no,
        "audit.xml",
    )

    # When
    inspection = inspect_archive(
        _archive(member_name=extended_name),
        limits=ArchiveLimits(),
    )

    # Then
    assert extended_name == "/20260312001119/audit.xml"
    assert inspection.ok is False
    assert inspection.data is None
    assert inspection.error is not None
    assert inspection.error.code is ErrorCode.PARSE_FAILED


def test_legacy_and_extended_attachments_coexist_and_select_fixed_bytes() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    source_rcept_no = "20260312001119"
    nested_member_name = f"{source_rcept_no}/audit.xml"
    requested_content = (
        "<document><title>요청 공시 감사보고서</title></document>"
    )
    source_content = (
        "<document><title>원본 공시 감사보고서</title></document>"
    )
    source = RecordingAttachmentSource(
        archives={
            requested_rcept_no: _archive(
                requested_content,
                nested_member_name,
            ),
            source_rcept_no: _archive(source_content),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={source_rcept_no}&amp;dcmNo=111">'
            "감사보고서</option>"
            "</select>"
        ).encode(),
    )
    service = AttachmentService(source)

    # When
    listing = service.list(requested_rcept_no)
    assert listing.data is not None
    selected = tuple(
        service.read_selected(requested_rcept_no, attachment)
        for attachment in listing.data
    )

    # Then
    assert listing.ok is True
    assert [attachment.attachment_id for attachment in listing.data] == [
        f"opendart:{requested_rcept_no}:{nested_member_name}",
        f"opendart:{requested_rcept_no}:/{source_rcept_no}/audit.xml",
    ]
    assert len({attachment.attachment_id for attachment in listing.data}) == 2
    assert [result.ok for result in selected] == [True, True]
    assert [result.data for result in selected] == [
        requested_content.encode(),
        source_content.encode(),
    ]


def test_export_accepts_identifier_from_successful_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_rcept_no = "20260515001658"
    attachment_id = f"opendart:{requested_rcept_no}:audit.xml"
    listed_attachment = Attachment(
        attachment_id=attachment_id,
        rcept_no=requested_rcept_no,
        source_rcept_no=requested_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )
    service, exported, read_ids, contexts = _configure_export(
        monkeypatch,
        tmp_path,
        Result.success((listed_attachment,)),
    )

    result = service.export_report_excel(requested_rcept_no, attachment_id)

    assert result.ok is True
    assert result.data == exported
    assert result.error is None
    assert read_ids == [attachment_id]
    assert contexts[0].source_rcept_no == requested_rcept_no


def test_export_proceeds_when_attachment_listing_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_rcept_no = "20260515001658"
    attachment_id = f"opendart:{requested_rcept_no}:audit.xml"
    listing_failure = Result[tuple[Attachment, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "DART 첨부 목록을 가져오지 못했습니다.",
            retryable=True,
        )
    )
    service, exported, read_ids, _contexts = _configure_export(
        monkeypatch,
        tmp_path,
        listing_failure,
    )

    result = service.export_report_excel(requested_rcept_no, attachment_id)

    assert result.ok is True
    assert result.data == exported
    assert result.error is None
    assert read_ids == [attachment_id]


def test_export_rejects_extended_identifier_when_attachment_listing_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    requested_rcept_no = "20260515001658"
    source_rcept_no = "20260312001119"
    attachment_id = (
        f"opendart:{requested_rcept_no}:/{source_rcept_no}/audit.xml"
    )
    listing_failure = Result[tuple[Attachment, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "DART 첨부 목록을 가져오지 못했습니다.",
            retryable=True,
        )
    )
    service, _exported, read_ids, contexts = _configure_export(
        monkeypatch,
        tmp_path,
        listing_failure,
    )

    def reject_uncorroborated_extended(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        assert rcept_no == requested_rcept_no
        assert selection == attachment_id
        read_ids.append(attachment_id)
        return Result.failure(
            error_info(
                ErrorCode.INVALID_INPUT,
                (
                    "확장 첨부 식별자는 성공한 "
                    "list_report_attachments 결과에서 확인되어야 합니다."
                ),
                retryable=False,
            )
        )

    monkeypatch.setattr(
        AttachmentService,
        "read_selected",
        reject_uncorroborated_extended,
    )

    # When
    result = service.export_report_excel(requested_rcept_no, attachment_id)

    # Then
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert "list_report_attachments" in result.error.message
    assert read_ids == [attachment_id]
    assert contexts == []


def test_export_accepts_ambiguous_legacy_identifier_when_listing_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_rcept_no = "20260515001658"
    member_name = "20260312001119/audit.xml"
    attachment_id = f"opendart:{requested_rcept_no}:{member_name}"
    listing_failure = Result[tuple[Attachment, ...]].failure(
        error_info(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "DART 첨부 목록을 가져오지 못했습니다.",
            retryable=True,
        )
    )
    service, exported, read_ids, contexts = _configure_export(
        monkeypatch,
        tmp_path,
        listing_failure,
    )

    result = service.export_report_excel(requested_rcept_no, attachment_id)

    assert result.ok is True
    assert result.data == exported
    assert result.error is None
    assert read_ids == [attachment_id]
    assert contexts[0].source_rcept_no == requested_rcept_no


def test_export_accepts_listed_extended_identifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    requested_rcept_no = "20260515001658"
    source_rcept_no = "20260312001119"
    attachment_id = (
        f"opendart:{requested_rcept_no}:/{source_rcept_no}/audit.xml"
    )
    listed_attachment = Attachment(
        attachment_id=attachment_id,
        rcept_no=requested_rcept_no,
        source_rcept_no=source_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )
    service, exported, read_ids, contexts = _configure_export(
        monkeypatch,
        tmp_path,
        Result.success((listed_attachment,)),
    )

    # When
    result = service.export_report_excel(requested_rcept_no, attachment_id)

    # Then
    assert result.ok is True
    assert result.data == exported
    assert result.error is None
    assert read_ids == [attachment_id]
    assert contexts[0].source_rcept_no == source_rcept_no


def test_export_uses_listing_metadata_for_ambiguous_legacy_identifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    requested_rcept_no = "20260515001658"
    apparent_source_rcept_no = "20260312001119"
    member_name = f"{apparent_source_rcept_no}/audit.xml"
    attachment_id = f"opendart:{requested_rcept_no}:{member_name}"
    listed_attachment = Attachment(
        attachment_id=attachment_id,
        rcept_no=requested_rcept_no,
        source_rcept_no=requested_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename=member_name,
    )
    service, exported, _read_ids, contexts = _configure_export(
        monkeypatch,
        tmp_path,
        Result.success((listed_attachment,)),
    )
    selections: list[str | Attachment] = []

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        assert rcept_no == requested_rcept_no
        selections.append(selection)
        return Result.success(_DEFAULT_MEMBER_CONTENT.encode())

    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)

    # When
    result = service.export_report_excel(requested_rcept_no, attachment_id)

    # Then
    assert result.ok is True
    assert result.data == exported
    assert selections == [listed_attachment]
    assert contexts[0].source_rcept_no == requested_rcept_no


def test_export_rejects_unlisted_extended_identifier_before_reading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_rcept_no = "20260515001658"
    listed_attachment = Attachment(
        attachment_id=f"opendart:{requested_rcept_no}:audit.xml",
        rcept_no=requested_rcept_no,
        source_rcept_no=requested_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )

    def find_disclosure(_self: DartApi, rcept_no: str) -> Result[DartListRow]:
        return Result.success(_disclosure(rcept_no))

    def list_attachments(
        _self: AttachmentService,
        rcept_no: str,
    ) -> Result[tuple[Attachment, ...]]:
        assert rcept_no == requested_rcept_no
        return Result.success((listed_attachment,))

    def read_selected(
        _self: AttachmentService,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[bytes]:
        raise AssertionError((rcept_no, attachment_id))

    monkeypatch.setattr(DartApi, "find_disclosure", find_disclosure)
    monkeypatch.setattr(AttachmentService, "list", list_attachments)
    monkeypatch.setattr(AttachmentService, "read_selected", read_selected)
    service = _crawler_service(tmp_path)

    result = service.export_report_excel(
        requested_rcept_no,
        (
            f"opendart:{requested_rcept_no}:"
            "20260310002820/another_company.xml"
        ),
    )

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert "list_report_attachments" in result.error.message


def test_read_selected_accepts_legacy_identifier() -> None:
    requested_rcept_no = "20260515001658"
    source = RecordingAttachmentSource({requested_rcept_no: _archive()})

    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        f"opendart:{requested_rcept_no}:audit.xml",
    )

    assert source.download_calls == [requested_rcept_no]
    assert result.ok is True
    assert result.data == "<document><title>감사보고서</title></document>".encode()
    assert result.error is None

def test_read_selected_accepts_legacy_nested_member_path() -> None:
    requested_rcept_no = "20260515001658"
    member_name = "2026031200111/foo.xml"
    source = RecordingAttachmentSource(
        {requested_rcept_no: _archive(member_name=member_name)}
    )

    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        f"opendart:{requested_rcept_no}:{member_name}",
    )

    assert source.download_calls == [requested_rcept_no]
    assert result.ok is True
    assert result.data == _DEFAULT_MEMBER_CONTENT.encode()
    assert result.error is None


def test_read_selected_prefers_legacy_when_path_starts_with_14_digits() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    apparent_source_rcept_no = "20260312001119"
    member_name = f"{apparent_source_rcept_no}/audit.xml"
    requested_content = "<document><title>요청 공시 감사보고서</title></document>"
    other_content = "<document><title>다른 공시 감사보고서</title></document>"
    source = RecordingAttachmentSource(
        {
            requested_rcept_no: _archive(requested_content, member_name),
            apparent_source_rcept_no: _archive(other_content),
        }
    )

    # When
    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        f"opendart:{requested_rcept_no}:{member_name}",
    )

    # Then
    assert source.download_calls == [requested_rcept_no]
    assert result.ok is True
    assert result.data == requested_content.encode()
    assert result.error is None


def test_read_selected_uses_listing_metadata_for_ambiguous_legacy_identifier() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    apparent_source_rcept_no = "20260312001119"
    member_name = f"{apparent_source_rcept_no}/audit.xml"
    requested_content = "<document><title>요청 공시 감사보고서</title></document>"
    other_content = "<document><title>다른 공시 감사보고서</title></document>"
    source = RecordingAttachmentSource(
        {
            requested_rcept_no: _archive(requested_content, member_name),
            apparent_source_rcept_no: _archive(other_content),
        }
    )
    listed_attachment = Attachment(
        attachment_id=f"opendart:{requested_rcept_no}:{member_name}",
        rcept_no=requested_rcept_no,
        source_rcept_no=requested_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename=member_name,
    )

    # When
    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        listed_attachment,
    )

    # Then
    assert source.download_calls == [requested_rcept_no]
    assert result.ok is True
    assert result.data == requested_content.encode()
    assert result.error is None


def test_read_selected_accepts_corroborated_extended_identifier() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    source_rcept_no = "20260312001119"
    attachment_id = (
        f"opendart:{requested_rcept_no}:/{source_rcept_no}/audit.xml"
    )
    source = RecordingAttachmentSource(
        {
            requested_rcept_no: _archive(member_name="unrelated.xml"),
            source_rcept_no: _archive(),
        }
    )
    listed_attachment = Attachment(
        attachment_id=attachment_id,
        rcept_no=requested_rcept_no,
        source_rcept_no=source_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="audit.xml",
    )

    # When
    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        listed_attachment,
    )

    # Then
    assert source.download_calls == [source_rcept_no]
    assert result.ok is True
    assert result.data == "<document><title>감사보고서</title></document>".encode()
    assert result.error is None


def test_read_selected_rejects_uncorroborated_extended_identifier() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    source_rcept_no = "20260312001119"
    attachment_id = (
        f"opendart:{requested_rcept_no}:/{source_rcept_no}/audit.xml"
    )
    source = RecordingAttachmentSource(
        {
            requested_rcept_no: _archive(member_name="unrelated.xml"),
            source_rcept_no: _archive(),
        }
    )

    # When
    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        attachment_id,
    )

    # Then
    assert source.download_calls == []
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
    assert "list_report_attachments" in (result.next_action or "")


@pytest.mark.parametrize(
    "malformed_name",
    [
        "/20260312001119/",
    ],
)
def test_read_selected_rejects_malformed_extended_identifier(
    malformed_name: str,
) -> None:
    requested_rcept_no = "20260515001658"
    source = RecordingAttachmentSource({requested_rcept_no: _archive()})

    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        f"opendart:{requested_rcept_no}:{malformed_name}",
    )

    assert source.download_calls == []
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT


def test_read_selected_rejects_empty_member_name() -> None:
    requested_rcept_no = "20260515001658"
    source = RecordingAttachmentSource({requested_rcept_no: _archive()})

    result = AttachmentService(source).read_selected(
        requested_rcept_no,
        f"opendart:{requested_rcept_no}:",
    )

    assert source.download_calls == []
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_INPUT
def test_xml_report_title_uses_word_count_only_without_statement_title() -> None:
    report = (
        "<document>"
        "<TITLE>독립된 감사인의 감사보고서</TITLE>"
        "<BODY>연결 연결 연결 별도</BODY>"
        "</document>"
    )
    rcept_no = "20260515001658"
    source = RecordingAttachmentSource({rcept_no: _archive(report)})

    result = AttachmentService(source).list(rcept_no)

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].title == "연결감사보고서"
    assert result.error is None
