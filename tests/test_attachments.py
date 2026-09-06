from dataclasses import dataclass, field
from io import BytesIO
from zipfile import ZipFile

import pytest

from dart_crawler.attachments import (
    AttachmentService,
    _is_report_title,
    _viewer_report_title,
    _xml_report_title,
)
from dart_crawler.domain import Attachment
from dart_crawler.result import ErrorCode, Result, error_info


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
    # One code covers three unrelated substitutions; the axis says which.
    assert result.warnings[0].details["fallback_axis"] == "source"


def test_viewer_fallback_reads_attachment_options() -> None:
    result = AttachmentService(ViewerOptionSource()).list("20260515002181")

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == "viewer:20260515002181:222"
    assert result.data[0].title == "\uc5f0\uacb0\ubd84\uae30\uac80\ud1a0\ubcf4\uace0\uc11c"


def _original_report_archive() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "20260312001119_00760.xml",
            "<document><title>\ubcc4\ub3c4\uac10\uc0ac\ubcf4\uace0\uc11c</title></document>",
        )
        archive.writestr(
            "20260312001119_00761.xml",
            "<document><title>\uc5f0\uacb0\uac10\uc0ac\ubcf4\uace0\uc11c</title></document>",
        )
    return buffer.getvalue()


def _single_report_archive(source_rcept_no: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"{source_rcept_no}_audit.xml",
            "<document><title>감사보고서</title></document>",
        )
    return buffer.getvalue()


@dataclass
class AttachmentSourceFake:
    documents: dict[str, bytes]
    viewer_html: bytes
    viewer_error_message: str | None = None
    download_calls: list[str] = field(default_factory=list)

    def download_document(self, rcept_no: str) -> Result[bytes]:
        self.download_calls.append(rcept_no)
        document = self.documents.get(rcept_no)
        if document is None:
            return Result.failure(
                error_info(
                    ErrorCode.NOT_FOUND,
                    "원본 공시 ZIP을 찾지 못했습니다.",
                    retryable=False,
                )
            )
        return Result.success(document)

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        if self.viewer_error_message is not None:
            return Result.failure(
                error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    self.viewer_error_message,
                    retryable=True,
                )
            )
        return Result.success(self.viewer_html)

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        return Result.success(b"")


def _requested_audit_archive(
    rcept_no: str,
    *,
    include_standalone: bool,
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        if include_standalone:
            archive.writestr(
                f"{rcept_no}_00760.xml",
                "<document><title>별도감사보고서</title></document>",
            )
        archive.writestr(
            f"{rcept_no}_00761.xml",
            "<document><title>연결감사보고서</title></document>",
        )
    return buffer.getvalue()


def _annual_viewer_options(
    standalone_rcept_no: str,
    consolidated_rcept_no: str,
) -> bytes:
    return (
        "<select>"
        f'<option value="rcpNo={standalone_rcept_no}&amp;dcmNo=11104491">'
        "별도감사보고서</option>"
        f'<option value="rcpNo={consolidated_rcept_no}&amp;dcmNo=11104492">'
        "연결감사보고서</option>"
        "</select>"
    ).encode()


def test_requested_zip_reports_replace_matching_viewer_records() -> None:
    # Given
    requested_rcept_no = "20260310002820"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: _requested_audit_archive(
                requested_rcept_no,
                include_standalone=True,
            ),
        },
        viewer_html=_annual_viewer_options(
            requested_rcept_no,
            requested_rcept_no,
        ),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [item.attachment_id for item in result.data] == [
        "opendart:20260310002820:20260310002820_00760.xml",
        "opendart:20260310002820:20260310002820_00761.xml",
    ]


def test_requested_zip_reports_exclude_statutory_auditor_report() -> None:
    # Given
    requested_rcept_no = "20260310002820"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: _requested_audit_archive(
                requested_rcept_no,
                include_standalone=True,
            ),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo=11104486">'
            "감사보고서</option>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo=11104487">'
            "연결감사보고서</option>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo=11104491">'
            "감사의감사보고서</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [(item.title, item.attachment_id) for item in result.data] == [
        (
            "별도감사보고서",
            "opendart:20260310002820:20260310002820_00760.xml",
        ),
        (
            "연결감사보고서",
            "opendart:20260310002820:20260310002820_00761.xml",
        ),
    ]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        pytest.param(
            "외국법인등의분기검토\u318d감사보고서",
            "별도분기검토보고서",
            id="foreign_issuer_quarterly_review_audit",
        ),
        pytest.param(
            "외국법인등의분기연결검토\u318d감사보고서",
            "연결분기검토보고서",
            id="foreign_issuer_quarterly_consolidated_review_audit",
        ),
        pytest.param(
            "외국법인등의감사보고서",
            "별도감사보고서",
            id="foreign_issuer_audit",
        ),
        pytest.param(
            "외국법인등의연결감사보고서",
            "연결감사보고서",
            id="foreign_issuer_consolidated_audit",
        ),
        pytest.param("감사보고서", "별도감사보고서", id="audit"),
        pytest.param(
            "연결감사보고서",
            "연결감사보고서",
            id="consolidated_audit",
        ),
        pytest.param(
            "반기검토보고서",
            "별도반기검토보고서",
            id="half_year_review",
        ),
        pytest.param(
            "연결반기재무제표검토보고서",
            "연결반기검토보고서",
            id="consolidated_half_year_financial_statement_review",
        ),
        pytest.param("감사의감사보고서", None, id="statutory_auditor"),
        pytest.param(
            "내부감시장치에대한감사의의견서",
            None,
            id="internal_monitoring_opinion",
        ),
        pytest.param(
            "내부회계관리제도운영보고서",
            None,
            id="internal_accounting_control",
        ),
        pytest.param("영업보고서", None, id="business_report"),
        pytest.param("자기주식보고서", None, id="treasury_stock_report"),
        pytest.param("정관", None, id="articles_of_incorporation"),
    ],
)
def test_report_title_acceptance_rule(
    title: str,
    expected: str | None,
) -> None:
    # When
    accepted = _is_report_title(title)

    # Then
    assert accepted is (expected is not None)
    if expected is not None:
        assert _viewer_report_title(title) == expected


def test_viewer_only_foreign_issuer_reports_are_listed() -> None:
    # Given
    requested_rcept_no = "20260528000907"
    source = AttachmentSourceFake(
        documents={requested_rcept_no: b"not-a-zip"},
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo=11409899">'
            "외국법인등의감사보고서</option>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo=11409903">'
            "외국법인등의연결감사보고서</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [(item.title, item.attachment_id) for item in result.data] == [
        ("별도감사보고서", "viewer:20260528000907:11409899"),
        ("연결감사보고서", "viewer:20260528000907:11409903"),
    ]


def test_requested_zip_partial_recovery_keeps_viewer_report() -> None:
    # Given
    requested_rcept_no = "20260310002820"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: _requested_audit_archive(
                requested_rcept_no,
                include_standalone=False,
            ),
        },
        viewer_html=_annual_viewer_options(
            requested_rcept_no,
            requested_rcept_no,
        ),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [item.attachment_id for item in result.data] == [
        "opendart:20260310002820:20260310002820_00761.xml",
        "viewer:20260310002820:11104491",
    ]


def test_requested_zip_recovery_ignores_viewer_source_receipt() -> None:
    # Given
    requested_rcept_no = "20260310002820"
    viewer_source_rcept_no = "20260307000123"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: _single_report_archive(requested_rcept_no),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={viewer_source_rcept_no}&amp;dcmNo=11104491">'
            "별도감사보고서</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [item.source for item in result.data] == ["opendart"]


@pytest.mark.parametrize(
    ("period_qualifier", "dcm_no"),
    [
        pytest.param("반기", "111", id="half_year"),
        pytest.param("분기", "222", id="quarter"),
    ],
)
def test_interim_zip_and_viewer_report_are_listed_once(
    period_qualifier: str,
    dcm_no: str,
) -> None:
    # Given
    requested_rcept_no = "20260811001234"
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "review.xml",
            (
                f"<document><title>{period_qualifier}재무제표 "
                "검토보고서</title></document>"
            ),
        )
    source = AttachmentSourceFake(
        documents={requested_rcept_no: archive_buffer.getvalue()},
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo={dcm_no}">'
            f"별도{period_qualifier}검토보고서"
            "</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [(item.title, item.source) for item in result.data] == [
        ("별도검토보고서", "opendart")
    ]


def test_requested_zip_warns_when_viewer_fetch_fails() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    viewer_failure_reason = "DART viewer 응답을 받지 못했습니다."
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: _single_report_archive(requested_rcept_no),
        },
        viewer_html=b"",
        viewer_error_message=viewer_failure_reason,
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 1
    assert result.warnings
    assert result.warnings[0].code.value == "VIEWER_DISCOVERY_SKIPPED"
    assert result.warnings[0].details["viewer_failure_reason"] == (
        viewer_failure_reason
    )


def test_viewer_failure_warning_keeps_partial_zip_rejection_details() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    rejected_member = "internal_review.xml"
    viewer_failure_reason = "DART viewer 응답을 받지 못했습니다."
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "audit.xml",
            "<document><title>감사보고서</title></document>",
        )
        archive.writestr(
            rejected_member,
            "<document><title>내부 검토 자료</title></document>",
        )
    source = AttachmentSourceFake(
        documents={requested_rcept_no: archive_buffer.getvalue()},
        viewer_html=b"",
        viewer_error_message=viewer_failure_reason,
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 1
    assert result.warnings
    details = result.warnings[0].details
    assert details["viewer_failure_reason"] == viewer_failure_reason
    assert rejected_member in str(details["requested_zip_reason"])
    assert "감사·검토보고서를 찾지 못했습니다." in str(
        details["requested_zip_reason"]
    )


def test_viewer_option_keeps_its_own_receipt_number() -> None:
    requested_rcept_no = "20260515001658"
    source = AttachmentSourceFake(
        documents={requested_rcept_no: b"not-a-zip"},
        viewer_html=(
            '<select><option value="rcpNo=20260312001119&amp;dcmNo=11115996">'
            "2026.05.15 \uac10\uc0ac\ubcf4\uace0\uc11c</option></select>"
        ).encode("utf-8"),
    )

    result = AttachmentService(source).list(requested_rcept_no)

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == (
        "viewer:20260515001658:/20260312001119/11115996"
    ), "viewer attachment IDs must retain the option's source receipt number"


def test_viewer_script_keeps_original_receipt_number() -> None:
    requested_rcept_no = "20260515001658"
    original_rcept_no = "20260312001119"
    source = AttachmentSourceFake(
        documents={requested_rcept_no: b"not-a-zip"},
        viewer_html=(
            "<html><head><title>감사보고서</title></head>"
            f"<script>viewDoc('{original_rcept_no}', '11115996');</script></html>"
        ).encode(),
    )

    result = AttachmentService(source).list(requested_rcept_no)

    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == (
        f"viewer:{requested_rcept_no}:/{original_rcept_no}/11115996"
    )
    assert result.data[0].source_rcept_no == original_rcept_no


def test_viewer_merge_prefers_page_stated_source_receipt() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    original_rcept_no = "20260312001119"
    dcm_no = "11115996"
    source = AttachmentSourceFake(
        documents={requested_rcept_no: b"not-a-zip"},
        viewer_html=(
            "<html><head><title>감사보고서</title></head><select>"
            f'<option value="dcmNo={dcm_no}">감사보고서</option>'
            "</select>"
            f"<script>viewDoc('{original_rcept_no}', '{dcm_no}');</script>"
            "</html>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == (
        f"viewer:{requested_rcept_no}:/{original_rcept_no}/{dcm_no}"
    )
    assert result.data[0].source_rcept_no == original_rcept_no


def test_viewer_merge_keeps_selectable_title_with_page_stated_receipt() -> None:
    # Given
    requested_rcept_no = "20260515001658"
    original_rcept_no = "20260312001119"
    dcm_no = "11115996"
    source = AttachmentSourceFake(
        documents={requested_rcept_no: b"not-a-zip"},
        viewer_html=(
            "<html><head><title>감사보고서</title></head><select>"
            f'<option value="dcmNo={dcm_no}">연결감사보고서</option>'
            "</select>"
            f"<script>viewDoc('{original_rcept_no}', '{dcm_no}');</script>"
            "</html>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert result.data[0].attachment_id == (
        f"viewer:{requested_rcept_no}:/{original_rcept_no}/{dcm_no}"
    )
    assert result.data[0].source_rcept_no == original_rcept_no
    assert result.data[0].title == "연결감사보고서"
    assert result.data[0].standalone is False


def test_attachments_fall_back_to_the_filing_that_holds_them() -> None:
    requested_rcept_no = "20260515001658"
    original_rcept_no = "20260312001119"
    missing_document = (
        "<result><status>014</status>"
        "<message>\ud30c\uc77c\uc774 \uc874\uc7ac\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.</message></result>"
    ).encode("utf-8")
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: missing_document,
            original_rcept_no: _original_report_archive(),
        },
        viewer_html=(
            '<select><option value="rcpNo=20260312001119&amp;dcmNo=11115996">'
            "2026.05.15 \uac10\uc0ac\ubcf4\uace0\uc11c</option></select>"
        ).encode("utf-8"),
    )

    result = AttachmentService(source).list(requested_rcept_no)

    assert result.ok is True
    assert result.data is not None
    assert [item.attachment_id for item in result.data] == [
        "opendart:20260515001658:/20260312001119/20260312001119_00760.xml",
        "opendart:20260515001658:/20260312001119/20260312001119_00761.xml",
    ], "corrected filings must use OpenDART attachments from the original filing"
    assert result.warnings, "using the original filing must emit a warning"
    assert (
        result.warnings[0].code.value == "ORIGINAL_FILING_SOURCE_USED"
    ), "using the original filing must emit ORIGINAL_FILING_SOURCE_USED"


def test_original_filing_recovery_collects_every_source_receipt() -> None:
    requested_rcept_no = "20220513000001"
    first_source = "20220512000853"
    second_source = "20220308000956"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: b"not-a-zip",
            first_source: _single_report_archive(first_source),
            second_source: _single_report_archive(second_source),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={first_source}&amp;dcmNo=111">감사보고서</option>'
            f'<option value="rcpNo={second_source}&amp;dcmNo=222">감사보고서</option>'
            "</select>"
        ).encode(),
    )

    result = AttachmentService(source).list(requested_rcept_no)

    assert result.ok is True
    assert result.data is not None
    assert [item.source_rcept_no for item in result.data] == [
        first_source,
        second_source,
    ]
    assert result.warnings[0].code.value == "ORIGINAL_FILING_SOURCE_USED"
    assert result.warnings[0].details["source_receipt_numbers"] == [
        first_source,
        second_source,
    ]
    assert result.warnings[0].details["source_receipt_count"] == 2


def test_partial_original_recovery_keeps_failed_source_and_warning_details() -> None:
    # Given
    requested_rcept_no = "20220513000001"
    recovered_source = "20220512000853"
    failed_source = "20220308000956"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: b"not-a-zip",
            recovered_source: _single_report_archive(recovered_source),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={recovered_source}&amp;dcmNo=111">'
            "감사보고서</option>"
            f'<option value="rcpNo={failed_source}&amp;dcmNo=222">'
            "감사보고서</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [item.source_rcept_no for item in result.data] == [
        recovered_source,
        failed_source,
    ]
    assert result.data[1].source == "viewer"
    assert failed_source in str(
        result.warnings[0].details["source_zip_reason"]
    )


def test_partial_archive_recovery_keeps_unrecovered_viewer_attachment() -> None:
    # Given
    requested_rcept_no = "20220513000001"
    source_rcept_no = "20220512000853"
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            f"{source_rcept_no}_audit.xml",
            "<document><title>감사보고서</title></document>",
        )
        archive.writestr(
            f"{source_rcept_no}_unrecognized.xml",
            "<document><title>내부 검토 자료</title></document>",
        )
    rejected_member = f"{source_rcept_no}_unrecognized.xml"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: b"not-a-zip",
            source_rcept_no: archive_buffer.getvalue(),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={source_rcept_no}&amp;dcmNo=111">'
            "감사보고서</option>"
            f'<option value="rcpNo={source_rcept_no}&amp;dcmNo=222">'
            "연결감사보고서</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [(item.title, item.source) for item in result.data] == [
        ("별도감사보고서", "opendart"),
        ("연결감사보고서", "viewer"),
    ]
    assert result.warnings
    source_reason = str(
        result.warnings[0].details["source_zip_reason"]
    )
    assert rejected_member in source_reason
    assert "감사·검토보고서를 찾지 못했습니다." in source_reason


def test_requested_zip_recovery_keeps_viewer_source_whose_archive_failed() -> None:
    # Given
    requested_rcept_no = "20220513000001"
    failed_source = "20220308000956"
    source = AttachmentSourceFake(
        documents={
            requested_rcept_no: _single_report_archive(requested_rcept_no),
        },
        viewer_html=(
            "<select>"
            f'<option value="rcpNo={requested_rcept_no}&amp;dcmNo=111">'
            "감사보고서</option>"
            f'<option value="rcpNo={failed_source}&amp;dcmNo=222">'
            "감사보고서</option>"
            "</select>"
        ).encode(),
    )

    # When
    result = AttachmentService(source).list(requested_rcept_no)

    # Then
    assert result.ok is True
    assert result.data is not None
    assert [item.source_rcept_no for item in result.data] == [
        requested_rcept_no,
        failed_source,
    ]
    assert result.data[1].source == "viewer"
    assert failed_source in str(
        result.warnings[0].details["source_zip_reason"]
    )


def test_read_selected_uses_the_source_receipt_number() -> None:
    requested_rcept_no = "20260515001658"
    original_rcept_no = "20260312001119"
    archive = _original_report_archive()
    source = AttachmentSourceFake(
        documents={requested_rcept_no: archive, original_rcept_no: archive},
        viewer_html=b"",
    )
    service = AttachmentService(source)
    attachment_id = (
        "opendart:20260515001658:"
        "/20260312001119/20260312001119_00760.xml"
    )
    listed_attachment = Attachment(
        attachment_id=attachment_id,
        rcept_no=requested_rcept_no,
        source_rcept_no=original_rcept_no,
        title="별도감사보고서",
        source="opendart",
        standalone=True,
        filename="20260312001119_00760.xml",
    )

    result = service.read_selected(requested_rcept_no, listed_attachment)

    assert source.download_calls == [original_rcept_no], (
        "unambiguous extended IDs must read only their corroborated source receipt"
    )
    assert result.ok is True, (
        "selected OpenDART attachments must download their source receipt"
    )
    assert result.data == (
        "<document><title>\ubcc4\ub3c4\uac10\uc0ac\ubcf4\uace0\uc11c</title></document>"
    ).encode("utf-8")

    rejected = service.read_selected(
        requested_rcept_no,
        "opendart:20260312001119:20260312001119_00760.xml",
    )

    assert rejected.ok is False
    assert rejected.error is not None
    assert rejected.error.code is ErrorCode.INVALID_INPUT


def test_separate_report_is_not_labelled_consolidated_by_word_counts() -> None:
    separate_report = (
        "<document>"
        "<TITLE>독립된 감사인의 감사보고서</TITLE>"
        "<TITLE>(첨부)재 무 제 표</TITLE>"
        f"<BODY>{'연결 ' * 14}{'별도 ' * 9}</BODY>"
        "</document>"
    ).encode()
    consolidated_report = (
        "<document>"
        "<TITLE>독립된 감사인의 감사보고서</TITLE>"
        "<TITLE>(첨부)연 결 재 무 제 표</TITLE>"
        "</document>"
    ).encode()

    assert _xml_report_title(separate_report) == "별도감사보고서"
    assert _xml_report_title(consolidated_report) == "연결감사보고서"

def test_xml_report_title_prefers_attached_statements_over_generic_mention() -> None:
    report = (
        "<document>"
        "<TITLE>독립된 감사인의 감사보고서</TITLE>"
        "<TITLE>재무제표에 대한 경영진의 책임</TITLE>"
        "<TITLE>(첨부)연결재무제표</TITLE>"
        "</document>"
    ).encode()

    result = _xml_report_title(report)

    assert result == "연결감사보고서"

def test_xml_report_title_keeps_consolidated_scope_from_report_title() -> None:
    # Given
    report = (
        "<document>"
        "<TITLE>독립된 감사인의 연결감사보고서</TITLE>"
        "<TITLE>(첨부)재무제표</TITLE>"
        "</document>"
    ).encode()

    # When
    result = _xml_report_title(report)

    # Then
    assert result == "연결감사보고서"
