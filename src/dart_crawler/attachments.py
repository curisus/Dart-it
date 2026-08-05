"""Attachment discovery from OpenDART ZIP files with DART viewer fallback."""

from __future__ import annotations

import re
from typing import Protocol

from bs4 import BeautifulSoup

from dart_crawler.domain import Attachment
from dart_crawler.result import ErrorCode, Result, WarningCode, WarningInfo, error_info
from dart_crawler.zip_safety import ArchiveLimits, inspect_archive, read_member


class AttachmentSource(Protocol):
    """Capabilities needed for report attachment discovery."""

    def download_document(self, rcept_no: str) -> Result[bytes]:
        raise NotImplementedError

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        raise NotImplementedError

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        raise NotImplementedError


class AttachmentService:
    """Find selectable separate and consolidated report attachments."""

    def __init__(self, source: AttachmentSource) -> None:
        self._source = source

    def list(self, rcept_no: str) -> Result[tuple[Attachment, ...]]:
        """Prefer OpenDART originals and fall back to the DART viewer."""
        document = self._source.download_document(rcept_no)
        if document.ok and document.data is not None:
            from_zip = _attachments_from_zip(rcept_no, document.data)
            if from_zip:
                return Result.success(from_zip)
        viewer = self._source.fetch_viewer_html(rcept_no)
        if not viewer.ok or viewer.data is None:
            return Result.failure(
                viewer.error
                if viewer.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "DART 웹 문서를 수집할 수 없습니다.",
                    retryable=True,
                ),
                next_action="DART 웹 문서를 다시 시도하세요.",
            )
        parsed = _attachments_from_viewer(rcept_no, viewer.data)
        if not parsed.ok or parsed.data is None:
            return Result.failure(
                parsed.error
                if parsed.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_LAYOUT_CHANGED,
                    "DART 웹 문서 구조를 판별할 수 없습니다.",
                    retryable=False,
                ),
                warnings=(
                    WarningInfo(
                        code=WarningCode.FALLBACK_SOURCE_USED,
                        message="OpenDART 원문 ZIP 대신 DART 웹 문서를 사용했습니다.",
                    ),
                ),
                next_action="DART 웹 문서 구조 변경 여부를 확인하세요.",
            )
        return Result.success(
            parsed.data,
            warnings=(
                WarningInfo(
                    code=WarningCode.FALLBACK_SOURCE_USED,
                    message="OpenDART 원문 ZIP 대신 DART 웹 문서를 사용했습니다.",
                ),
            ),
        )

    def read_selected(
        self,
        rcept_no: str,
        attachment_id: str,
    ) -> Result[bytes]:
        """Read the selected attachment content identified by the public ID."""
        parts = attachment_id.split(":", maxsplit=2)
        if len(parts) != 3 or parts[1] != rcept_no:
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    "첨부 식별자가 접수번호와 일치하지 않습니다.",
                    retryable=False,
                )
            )
        source, _, name = parts
        if source == "opendart":
            document = self._source.download_document(rcept_no)
            if not document.ok or document.data is None:
                return Result.failure(
                    document.error
                    if document.error is not None
                    else error_info(
                        ErrorCode.UPSTREAM_UNAVAILABLE,
                        "OpenDART 원문을 수집할 수 없습니다.",
                        retryable=True,
                    )
                )
            return read_member(document.data, name, limits=ArchiveLimits())
        if source == "viewer":
            viewer = self._source.fetch_viewer_document(rcept_no, name)
            if viewer.ok and viewer.data is not None:
                return Result.success(viewer.data)
            return Result.failure(
                viewer.error
                if viewer.error is not None
                else error_info(
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                    "DART 웹 문서를 수집할 수 없습니다.",
                    retryable=True,
                )
            )
        return Result.failure(
            error_info(
                ErrorCode.INVALID_INPUT,
                "지원하지 않는 첨부 식별자 형식입니다.",
                retryable=False,
            )
        )


def _attachments_from_zip(rcept_no: str, content: bytes) -> tuple[Attachment, ...]:
    inspection = inspect_archive(content, limits=ArchiveLimits())
    if not inspection.ok or inspection.data is None:
        return ()
    attachments: list[Attachment] = []
    for member in sorted(inspection.data, key=lambda item: item.name):
        if not member.name.casefold().endswith(".xml"):
            continue
        if member.name.casefold() == f"{rcept_no}.xml":
            continue
        xml = read_member(content, member.name, limits=ArchiveLimits())
        if not xml.ok or xml.data is None:
            continue
        title = _xml_report_title(xml.data)
        if title is None:
            continue
        if not _is_report_title(title):
            continue
        attachments.append(
            Attachment(
                attachment_id=f"opendart:{rcept_no}:{member.name}",
                rcept_no=rcept_no,
                title=title,
                source="opendart",
                standalone="연결" not in title,
                filename=member.name,
            )
        )
    return tuple(attachments)


def _attachments_from_viewer(
    rcept_no: str,
    content: bytes,
) -> Result[tuple[Attachment, ...]]:
    soup = BeautifulSoup(content, "lxml")
    attachments = _merge_viewer_attachments(
        (
            _viewer_option_attachments(rcept_no, soup),
            _viewer_link_attachments(rcept_no, soup),
            _viewer_script_attachments(rcept_no, soup, content),
        )
    )
    if not attachments:
        return Result.failure(
            error_info(
                ErrorCode.UPSTREAM_LAYOUT_CHANGED,
                "DART 웹 문서에서 선택 가능한 보고서를 찾지 못했습니다.",
                retryable=False,
            )
        )
    return Result.success(attachments)


def _viewer_option_attachments(
    rcept_no: str,
    soup: BeautifulSoup,
) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    for option in soup.select("option[value]"):
        value = option.get("value")
        title = _viewer_report_title(option.get_text(" ", strip=True))
        if not isinstance(value, str) or not _is_report_title(title):
            continue
        dcm_match = re.search(r"(?:^|[?&])dcmNo=(\d+)", value)
        if dcm_match is None:
            continue
        dcm_no = dcm_match.group(1)
        attachments.append(_viewer_attachment(rcept_no, dcm_no, title))
    return tuple(attachments)


def _viewer_link_attachments(
    rcept_no: str,
    soup: BeautifulSoup,
) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    for link in soup.select("a[href]"):
        href = link.get("href")
        title = _viewer_report_title(link.get_text(" ", strip=True))
        if not isinstance(href, str) or not _is_report_title(title):
            continue
        dcm_match = re.search(r"(?:[?&])dcmNo=(\d+)", href)
        if dcm_match is None:
            continue
        dcm_no = dcm_match.group(1)
        attachments.append(_viewer_attachment(rcept_no, dcm_no, title))
    return tuple(attachments)


def _viewer_script_attachments(
    rcept_no: str,
    soup: BeautifulSoup,
    content: bytes,
) -> tuple[Attachment, ...]:
    page_title = _viewer_report_title(
        soup.title.get_text(" ", strip=True) if soup.title else ""
    )
    if not _is_report_title(page_title):
        return ()
    attachments: list[Attachment] = []
    for match in re.finditer(
        r"viewDoc\(\s*[\"'](\d{14})[\"']\s*,\s*[\"'](\d+)[\"']",
        content.decode("utf-8", errors="replace"),
        flags=re.IGNORECASE,
    ):
        if match.group(1) != rcept_no or not _is_report_title(page_title):
            continue
        dcm_no = match.group(2)
        attachments.append(_viewer_attachment(rcept_no, dcm_no, page_title))
    return tuple(attachments)


def _viewer_attachment(rcept_no: str, dcm_no: str, title: str) -> Attachment:
    return Attachment(
        attachment_id=f"viewer:{rcept_no}:{dcm_no}",
        rcept_no=rcept_no,
        title=title,
        source="viewer",
        standalone="연결" not in title,
        dcm_no=dcm_no,
    )


def _merge_viewer_attachments(
    groups: tuple[tuple[Attachment, ...], ...],
) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    seen: set[str] = set()
    for group in groups:
        for attachment in group:
            if attachment.dcm_no is None or attachment.dcm_no in seen:
                continue
            seen.add(attachment.dcm_no)
            attachments.append(attachment)
    return tuple(attachments)


def _viewer_report_title(title: str) -> str:
    compact = " ".join(title.split())
    consolidated = "연결" in compact
    if "분기" in compact and "검토보고서" in compact:
        base = "분기검토보고서"
    elif "반기" in compact and "검토보고서" in compact:
        base = "반기검토보고서"
    elif "감사보고서" in compact:
        base = "감사보고서"
    elif "검토보고서" in compact:
        base = "검토보고서"
    else:
        return compact
    return f"{'연결' if consolidated else '별도'}{base}"


def _is_report_title(title: str) -> bool:
    return any(
        keyword in title
        for keyword in (
            "감사보고서",
            "검토보고서",
        )
    )


def _xml_report_title(content: bytes) -> str | None:
    soup = BeautifulSoup(content, "xml")
    title_nodes = soup.find_all(["TITLE", "title"])
    full_text = soup.get_text(" ", strip=True)
    base_title: str | None = None
    for node in title_nodes:
        title = node.get_text(" ", strip=True)
        for candidate in (
            "연결반기재무제표 검토보고서",
            "반기재무제표 검토보고서",
            "연결분기재무제표 검토보고서",
            "분기재무제표 검토보고서",
            "연결감사보고서",
            "감사보고서",
            "연결검토보고서",
            "검토보고서",
        ):
            if candidate in title:
                base_title = "검토보고서" if "검토" in candidate else "감사보고서"
                break
        if base_title is not None:
            break
    if base_title is None:
        return None
    consolidated = full_text.count("연결") > full_text.count("별도")
    return f"{'연결' if consolidated else '별도'}{base_title}"
