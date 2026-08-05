from dataclasses import dataclass
from io import BytesIO
from zipfile import ZipFile

from dart_crawler.attachments import AttachmentService
from dart_crawler.result import Result


def _report_archive() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("audit.xml", "<document><title>감사보고서</title></document>")
        archive.writestr(
            "consolidated.xml",
            "<document><title>연결감사보고서</title></document>",
        )
    return buffer.getvalue()


@dataclass
class ZipSource:
    def download_document(self, rcept_no: str) -> Result[bytes]:
        return Result.success(_report_archive())

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        return Result.success(b"")

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        return Result.success(b"")


@dataclass
class ViewerSource:
    def download_document(self, rcept_no: str) -> Result[bytes]:
        return Result.success(b"not-a-zip")

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        html = (
            '<html><a href="/dsaf001/sub.do?rcpNo=20260310002820&dcmNo=111">'
            "연결재무제표 검토보고서</a></html>"
        )
        return Result.success(html.encode("utf-8"))

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        return Result.success("<html><h1>검토보고서</h1></html>".encode())


@dataclass
class ViewerOptionSource:
    def download_document(self, rcept_no: str) -> Result[bytes]:
        return Result.success(b"not-a-zip")

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        html = (
            '<select><option value="rcpNo=20260515002181&amp;dcmNo=222">'
            "2026.05.15 \ubd84\uae30\uc5f0\uacb0\uac80\ud1a0\ubcf4\uace0\uc11c</option></select>"
        )
        return Result.success(html.encode("utf-8"))

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        return Result.success(b"<html><h1>report</h1></html>")


def test_zip_attachments_use_fixed_opendart_identifiers() -> None:
    result = AttachmentService(ZipSource()).list("20260310002820")

    assert result.ok is True
    assert result.data is not None
    assert [item.attachment_id for item in result.data] == [
        "opendart:20260310002820:audit.xml",
        "opendart:20260310002820:consolidated.xml",
    ]


def test_viewer_fallback_uses_fixed_viewer_identifier() -> None:
    result = AttachmentService(ViewerSource()).list("20260310002820")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == "viewer:20260310002820:111"
    assert result.warnings[0].code.value == "FALLBACK_SOURCE_USED"


def test_viewer_fallback_reads_attachment_options() -> None:
    result = AttachmentService(ViewerOptionSource()).list("20260515002181")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == "viewer:20260515002181:222"
    assert result.data[0].title == "\uc5f0\uacb0\ubd84\uae30\uac80\ud1a0\ubcf4\uace0\uc11c"
