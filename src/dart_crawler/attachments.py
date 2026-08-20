"""Attachment discovery from OpenDART ZIP files with DART viewer fallback."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, Protocol, assert_never

from bs4 import BeautifulSoup

from dart_crawler.domain import Attachment
from dart_crawler.result import (
    ErrorCode,
    JsonObject,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)
from dart_crawler.statement_lexicon import compact
from dart_crawler.zip_safety import (
    ArchiveLimits,
    ArchiveMember,
    inspect_archive,
    read_member,
)

# An inspected ZIP rejects absolute member paths, so a safe legacy member can
# never begin with this marker. No extended identifier has been published:
# every change in this review round is still uncommitted, so no migration path
# is needed for the former overlapping encoding.
_EXTENDED_NAME_MARKER: Final = "/"
# U+318D is escaped because Ruff RUF001 flags pasted confusable characters.
_REVIEW_REPORT_SUFFIXES: Final = (
    "검토\u318d감사보고서",
    "검토보고서",
)
_REPORT_TITLE_SUFFIXES: Final = (*_REVIEW_REPORT_SUFFIXES, "감사보고서")
_REPORT_TITLE_PATTERN: Final = re.compile(
    rf"(?:{'|'.join(map(re.escape, _REPORT_TITLE_SUFFIXES))})\Z"
)
# Each exclusion entry below was observed in a real DART filing.
_REPORT_TITLE_START_EXCLUSIONS: Final = frozenset({"내부"})
_REPORT_TITLE_SUFFIX_PREFIX_EXCLUSIONS: Final = frozenset({"감사의"})
_VIEWER_DATE_PREFIX_PATTERN: Final = re.compile(r"^\s*\d{4}\.\d{2}\.\d{2}\s*")

class AttachmentSource(Protocol):
    """Capabilities needed for report attachment discovery."""

    def download_document(self, rcept_no: str) -> Result[bytes]:
        raise NotImplementedError

    def fetch_viewer_html(self, rcept_no: str) -> Result[bytes]:
        raise NotImplementedError

    def fetch_viewer_document(self, rcept_no: str, dcm_no: str) -> Result[bytes]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _ZipAttachmentResult:
    """Attachments found in a ZIP and member-level rejection reasons."""

    attachments: tuple[Attachment, ...]
    rejection_reasons: tuple[str, ...] = ()


@unique
class _ZipMemberOutcome(StrEnum):
    """Mutually exclusive diagnostic for one ZIP member."""

    NOT_XML = "not_xml"
    SELF_DOCUMENT = "self_document"
    READ_FAILED = "read_failed"
    NOT_A_REPORT = "not_a_report"
    ACCEPTED = "accepted"


@unique
class _ZipRejectionKind(StrEnum):
    """Aggregate reason why a ZIP yielded no report attachments."""

    NO_XML = "no_xml"
    SELF_DOCUMENT = "self_document"
    READ_FAILED = "read_failed"
    NOT_A_REPORT = "not_a_report"


@dataclass(frozen=True, slots=True)
class _ZipMemberResult:
    """Result of applying the ZIP member attachment filters."""

    outcome: _ZipMemberOutcome
    attachment: Attachment | None = None


@dataclass(frozen=True, slots=True)
class _OriginalZipResult:
    """Original filing ZIP outcome for viewer-discovered source receipts."""

    attachments: tuple[Attachment, ...]
    source_rcept_nos: tuple[str, ...]
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ViewerAttachmentCandidate:
    """Viewer attachment with independent source-receipt and title provenance."""

    attachment: Attachment
    source_receipt_stated: bool
    title_from_selectable: bool


@dataclass(frozen=True, slots=True)
class _AttachmentReadTarget:
    """Resolved archive or viewer member selected for reading."""

    source: str
    source_rcept_no: str
    member_name: str
    listing_corroborated: bool

class AttachmentService:
    """Find selectable separate and consolidated report attachments."""

    def __init__(self, source: AttachmentSource) -> None:
        self._source = source

    def list(self, rcept_no: str) -> Result[tuple[Attachment, ...]]:
        """Collect requested and viewer-named filing sources without omissions."""
        document = self._source.download_document(rcept_no)
        requested_attachments: tuple[Attachment, ...] = ()
        requested_zip_reason: str | None
        if document.ok and document.data is not None:
            from_zip = _attachments_from_zip(rcept_no, document.data)
            requested_attachments = from_zip.attachments
            requested_zip_reason = (
                "; ".join(from_zip.rejection_reasons)
                if from_zip.rejection_reasons
                else None
            )
        else:
            requested_zip_reason = (
                document.error.message
                if document.error is not None
                else "OpenDART 원문 ZIP을 수집하지 못했습니다."
            )
        viewer = self._source.fetch_viewer_html(rcept_no)
        if not viewer.ok or viewer.data is None:
            if requested_attachments:
                viewer_failure_reason = (
                    viewer.error.message
                    if viewer.error is not None
                    else "DART 웹 문서를 수집하지 못했습니다."
                )
                return Result.success(
                    requested_attachments,
                    warnings=(
                        _viewer_discovery_warning(
                            viewer_failure_reason,
                            requested_zip_reason,
                        ),
                    ),
                )
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
            if requested_attachments:
                viewer_failure_reason = (
                    parsed.error.message
                    if parsed.error is not None
                    else "DART 웹 문서 구조를 판별하지 못했습니다."
                )
                return Result.success(
                    requested_attachments,
                    warnings=(
                        _viewer_discovery_warning(
                            viewer_failure_reason,
                            requested_zip_reason,
                        ),
                    ),
                )
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
                        details=_zip_warning_details(requested_zip_reason),
                    ),
                ),
                next_action="DART 웹 문서 구조 변경 여부를 확인하세요.",
            )
        original_zip = self._original_filing_attachments(rcept_no, parsed.data)
        original_recovered = tuple(
            attachment
            for attachment in original_zip.attachments
            if attachment.source != "viewer"
        )
        viewer_recovery = original_recovered + _unrecovered_viewer_attachments(
            tuple(
                attachment
                for attachment in original_zip.attachments
                if attachment.source == "viewer"
            ),
            requested_attachments,
        )
        collected = requested_attachments + viewer_recovery
        source_reason = (
            "; ".join(original_zip.rejection_reasons)
            if original_zip.rejection_reasons
            else None
        )
        if original_zip.source_rcept_nos:
            source_label = (
                "여러 원본 공시"
                if len(original_zip.source_rcept_nos) > 1
                else "원본 공시"
            )
            source_numbers = ", ".join(original_zip.source_rcept_nos)
            if requested_attachments:
                message = (
                    f"요청 공시와 {source_label}(접수번호 {source_numbers})에서 "
                    "원문을 함께 수집했습니다."
                )
            else:
                message = (
                    f"정정공시에 첨부가 없어 {source_label}"
                    f"(접수번호 {source_numbers})에서 원문을 수집했습니다."
                )
            return Result.success(
                collected,
                warnings=(
                    WarningInfo(
                        code=WarningCode.ORIGINAL_FILING_SOURCE_USED,
                        message=message,
                        details=_zip_warning_details(
                            requested_zip_reason,
                            source_reason,
                            source_rcept_nos=original_zip.source_rcept_nos,
                        ),
                    ),
                ),
            )
        if requested_attachments:
            if requested_zip_reason is None and source_reason is None:
                return Result.success(collected)
            return Result.success(
                collected,
                warnings=(
                    WarningInfo(
                        code=WarningCode.PARTIAL_COLLECTION,
                        message=(
                            "일부 ZIP 첨부를 수집하지 못해 DART 웹 첨부를 "
                            "함께 반환했습니다."
                        ),
                        details=_zip_warning_details(requested_zip_reason, source_reason),
                    ),
                ),
            )
        return Result.success(
            original_zip.attachments,
            warnings=(
                WarningInfo(
                    code=WarningCode.FALLBACK_SOURCE_USED,
                    message="OpenDART 원문 ZIP 대신 DART 웹 문서를 사용했습니다.",
                    details=_zip_warning_details(
                        requested_zip_reason,
                        source_reason,
                    ),
                ),
            ),
        )

    def _original_filing_attachments(
        self,
        rcept_no: str,
        viewer_attachments: tuple[Attachment, ...],
    ) -> _OriginalZipResult:
        """Try ZIP files for receipts named by viewer attachments."""
        rejection_reasons: list[str] = []
        recovered_attachments: list[Attachment] = []
        contributing_sources: list[str] = []
        seen_sources: set[str] = set()
        for attachment in viewer_attachments:
            source_rcept_no = attachment.source_rcept_no
            if source_rcept_no == rcept_no or source_rcept_no in seen_sources:
                continue
            seen_sources.add(source_rcept_no)
            original_document = self._source.download_document(source_rcept_no)
            if not original_document.ok or original_document.data is None:
                rejection_reasons.append(
                    f"{source_rcept_no}: "
                    + (
                        original_document.error.message
                        if original_document.error is not None
                        else "원본 공시 ZIP을 수집하지 못했습니다."
                    )
                )
                continue
            original_zip = _attachments_from_zip(
                rcept_no,
                original_document.data,
                source_rcept_no=source_rcept_no,
            )
            rejection_reasons.extend(
                f"{source_rcept_no}: {reason}"
                for reason in original_zip.rejection_reasons
            )
            if original_zip.attachments:
                recovered_attachments.extend(original_zip.attachments)
                contributing_sources.append(source_rcept_no)
        viewer_fallbacks = _unrecovered_viewer_attachments(
            viewer_attachments,
            tuple(recovered_attachments),
        )
        return _OriginalZipResult(
            tuple(recovered_attachments) + viewer_fallbacks,
            tuple(contributing_sources),
            tuple(rejection_reasons),
        )

    def read_selected(
        self,
        rcept_no: str,
        selection: str | Attachment,
    ) -> Result[bytes]:
        """Read selected content using listing metadata when it is available."""
        resolved = _attachment_read_target(rcept_no, selection)
        if not resolved.ok or resolved.data is None:
            return Result.failure(
                resolved.error
                if resolved.error is not None
                else error_info(
                    ErrorCode.INVALID_INPUT,
                    "첨부 식별자 형식이 올바르지 않습니다.",
                    retryable=False,
                )
            )
        target = resolved.data
        if (
            target.source_rcept_no != rcept_no
            and not target.listing_corroborated
        ):
            return Result.failure(
                error_info(
                    ErrorCode.INVALID_INPUT,
                    (
                        "확장 첨부 식별자는 성공한 "
                        "list_report_attachments 결과에서 확인되어야 합니다."
                    ),
                    retryable=False,
                ),
                next_action="list_report_attachments를 다시 호출해 첨부를 선택하세요.",
            )
        if target.source == "opendart":
            return _read_opendart_attachment(self._source, target)
        if target.source == "viewer":
            viewer = self._source.fetch_viewer_document(
                target.source_rcept_no,
                target.member_name,
            )
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


def _read_opendart_attachment(
    source: AttachmentSource,
    target: _AttachmentReadTarget,
) -> Result[bytes]:
    """Read the exact ZIP member named by an unambiguous target."""
    document = source.download_document(target.source_rcept_no)
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
    return read_member(
        document.data,
        target.member_name,
        limits=ArchiveLimits(),
    )


def _attachment_read_target(
    rcept_no: str,
    selection: str | Attachment,
) -> Result[_AttachmentReadTarget]:
    """Resolve a public identifier without losing authoritative listing data."""
    match selection:
        case Attachment() as attachment:
            if attachment.rcept_no != rcept_no:
                return Result.failure(
                    error_info(
                        ErrorCode.INVALID_INPUT,
                        "첨부 식별자가 접수번호와 일치하지 않습니다.",
                        retryable=False,
                    )
                )
            selected_name = (
                attachment.filename
                if attachment.source == "opendart"
                else attachment.dcm_no
            )
            if selected_name is None:
                return Result.failure(
                    error_info(
                        ErrorCode.INVALID_INPUT,
                        "첨부 식별자 이름 형식이 올바르지 않습니다.",
                        retryable=False,
                    )
                )
            return Result.success(
                _AttachmentReadTarget(
                    source=attachment.source,
                    source_rcept_no=attachment.source_rcept_no,
                    member_name=selected_name,
                    listing_corroborated=True,
                )
            )
        case str() as attachment_id:
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
            extended = name.startswith(_EXTENDED_NAME_MARKER)
            if extended:
                source_rcept_no, separator, member_name = name.removeprefix(
                    _EXTENDED_NAME_MARKER
                ).partition(_EXTENDED_NAME_MARKER)
            else:
                source_rcept_no = rcept_no
                separator = ""
                member_name = name
            if not member_name or (
                extended
                and (
                    separator != _EXTENDED_NAME_MARKER
                    or re.fullmatch(r"\d{14}", source_rcept_no) is None
                )
            ):
                return Result.failure(
                    error_info(
                        ErrorCode.INVALID_INPUT,
                        "첨부 식별자 이름 형식이 올바르지 않습니다.",
                        retryable=False,
                    )
                )
            return Result.success(
                _AttachmentReadTarget(
                    source=source,
                    source_rcept_no=source_rcept_no,
                    member_name=member_name,
                    listing_corroborated=False,
                )
            )
        case unreachable:
            assert_never(unreachable)


def _attachments_from_zip(
    rcept_no: str,
    content: bytes,
    *,
    source_rcept_no: str | None = None,
) -> _ZipAttachmentResult:
    source_rcept_no = source_rcept_no or rcept_no
    inspection = inspect_archive(content, limits=ArchiveLimits())
    if not inspection.ok or inspection.data is None:
        inspection_rejection_reason = (
            inspection.error.message
            if inspection.error is not None
            else "ZIP 구조를 검사하지 못했습니다."
        )
        return _ZipAttachmentResult((), (inspection_rejection_reason,))
    attachments: list[Attachment] = []
    rejection_reasons: list[str] = []
    outcomes: Counter[_ZipMemberOutcome] = Counter()
    for member in sorted(inspection.data, key=lambda item: item.name):
        member_result = _zip_member_attachment(
            rcept_no,
            source_rcept_no,
            content,
            member,
        )
        outcomes[member_result.outcome] += 1
        if member_result.attachment is not None:
            attachments.append(member_result.attachment)
            continue
        member_rejection_reason = _zip_member_rejection_reason(
            member.name,
            member_result.outcome,
        )
        if member_rejection_reason is not None:
            rejection_reasons.append(member_rejection_reason)
    if attachments:
        return _ZipAttachmentResult(
            tuple(attachments),
            tuple(rejection_reasons),
        )
    return _ZipAttachmentResult(
        (),
        (_zip_rejection_reason(outcomes),),
    )


def _zip_member_attachment(
    rcept_no: str,
    source_rcept_no: str,
    content: bytes,
    member: ArchiveMember,
) -> _ZipMemberResult:
    """Apply ZIP member filters and build one report attachment."""
    if not member.name.casefold().endswith(".xml"):
        return _ZipMemberResult(outcome=_ZipMemberOutcome.NOT_XML)
    if member.name.casefold() == f"{source_rcept_no}.xml":
        return _ZipMemberResult(outcome=_ZipMemberOutcome.SELF_DOCUMENT)
    xml = read_member(content, member.name, limits=ArchiveLimits())
    if not xml.ok or xml.data is None:
        return _ZipMemberResult(outcome=_ZipMemberOutcome.READ_FAILED)
    title = _xml_report_title(xml.data)
    if title is None or not _is_report_title(title):
        return _ZipMemberResult(outcome=_ZipMemberOutcome.NOT_A_REPORT)
    return _ZipMemberResult(
        outcome=_ZipMemberOutcome.ACCEPTED,
        attachment=Attachment(
            attachment_id=(
                f"opendart:{rcept_no}:"
                f"{_attachment_name(rcept_no, source_rcept_no, member.name)}"
            ),
            rcept_no=rcept_no,
            source_rcept_no=source_rcept_no,
            title=title,
            source="opendart",
            standalone="연결" not in title,
            filename=member.name,
        ),
    )


def _zip_member_rejection_reason(
    member_name: str,
    outcome: _ZipMemberOutcome,
) -> str | None:
    """Describe an unexpected rejected XML member in a partial archive."""
    match outcome:
        case _ZipMemberOutcome.READ_FAILED:
            return f"{member_name}: ZIP 첨부 XML을 읽지 못했습니다."
        case _ZipMemberOutcome.NOT_A_REPORT:
            return f"{member_name}: 감사·검토보고서를 찾지 못했습니다."
        case (
            _ZipMemberOutcome.NOT_XML
            | _ZipMemberOutcome.SELF_DOCUMENT
            | _ZipMemberOutcome.ACCEPTED
        ):
            return None
        case unreachable:
            assert_never(unreachable)


def _zip_rejection_reason(
    outcomes: Counter[_ZipMemberOutcome],
) -> str:
    """Explain which ZIP attachment filter rejected the archive."""
    has_xml = any(
        outcomes[outcome] > 0
        for outcome in (
            _ZipMemberOutcome.SELF_DOCUMENT,
            _ZipMemberOutcome.READ_FAILED,
            _ZipMemberOutcome.NOT_A_REPORT,
            _ZipMemberOutcome.ACCEPTED,
        )
    )
    has_candidate = any(
        outcomes[outcome] > 0
        for outcome in (
            _ZipMemberOutcome.READ_FAILED,
            _ZipMemberOutcome.NOT_A_REPORT,
            _ZipMemberOutcome.ACCEPTED,
        )
    )
    if not has_xml:
        rejection = _ZipRejectionKind.NO_XML
    elif not has_candidate:
        rejection = _ZipRejectionKind.SELF_DOCUMENT
    elif (
        outcomes[_ZipMemberOutcome.READ_FAILED] > 0
        and outcomes[_ZipMemberOutcome.NOT_A_REPORT] == 0
        and outcomes[_ZipMemberOutcome.ACCEPTED] == 0
    ):
        rejection = _ZipRejectionKind.READ_FAILED
    else:
        rejection = _ZipRejectionKind.NOT_A_REPORT
    match rejection:
        case _ZipRejectionKind.NO_XML:
            return "ZIP에 XML 첨부가 없습니다."
        case _ZipRejectionKind.SELF_DOCUMENT:
            return "ZIP에 공시 원문 XML만 있습니다."
        case _ZipRejectionKind.READ_FAILED:
            return "ZIP 첨부 XML을 읽지 못했습니다."
        case _ZipRejectionKind.NOT_A_REPORT:
            return "ZIP XML에서 감사·검토보고서를 찾지 못했습니다."
        case unreachable:
            assert_never(unreachable)


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
) -> tuple[_ViewerAttachmentCandidate, ...]:
    attachments: list[_ViewerAttachmentCandidate] = []
    for option in soup.select("option[value]"):
        value = option.get("value")
        report_label = _viewer_report_label(option.get_text(" ", strip=True))
        if not isinstance(value, str) or not _is_report_title(report_label):
            continue
        title = _viewer_report_title(report_label)
        source_match = re.search(r"(?:^|[?&])rcpNo=(\d{14})", value)
        source_rcept_no = source_match.group(1) if source_match else rcept_no
        dcm_match = re.search(r"(?:^|[?&])dcmNo=(\d+)", value)
        if dcm_match is None:
            continue
        dcm_no = dcm_match.group(1)
        attachments.append(
            _ViewerAttachmentCandidate(
                attachment=_viewer_attachment(
                    rcept_no,
                    source_rcept_no,
                    dcm_no,
                    title,
                ),
                source_receipt_stated=source_match is not None,
                title_from_selectable=True,
            )
        )
    return tuple(attachments)


def _viewer_link_attachments(
    rcept_no: str,
    soup: BeautifulSoup,
) -> tuple[_ViewerAttachmentCandidate, ...]:
    attachments: list[_ViewerAttachmentCandidate] = []
    for link in soup.select("a[href]"):
        href = link.get("href")
        report_label = _viewer_report_label(link.get_text(" ", strip=True))
        if not isinstance(href, str) or not _is_report_title(report_label):
            continue
        title = _viewer_report_title(report_label)
        source_match = re.search(r"(?:^|[?&])rcpNo=(\d{14})", href)
        source_rcept_no = source_match.group(1) if source_match else rcept_no
        dcm_match = re.search(r"(?:[?&])dcmNo=(\d+)", href)
        if dcm_match is None:
            continue
        dcm_no = dcm_match.group(1)
        attachments.append(
            _ViewerAttachmentCandidate(
                attachment=_viewer_attachment(
                    rcept_no,
                    source_rcept_no,
                    dcm_no,
                    title,
                ),
                source_receipt_stated=source_match is not None,
                title_from_selectable=True,
            )
        )
    return tuple(attachments)


def _viewer_script_attachments(
    rcept_no: str,
    soup: BeautifulSoup,
    content: bytes,
) -> tuple[_ViewerAttachmentCandidate, ...]:
    page_label = _viewer_report_label(
        soup.title.get_text(" ", strip=True) if soup.title else ""
    )
    if not _is_report_title(page_label):
        return ()
    page_title = _viewer_report_title(page_label)
    attachments: list[_ViewerAttachmentCandidate] = []
    for match in re.finditer(
        r"viewDoc\(\s*[\"'](\d{14})[\"']\s*,\s*[\"'](\d+)[\"']",
        content.decode("utf-8", errors="replace"),
        flags=re.IGNORECASE,
    ):
        source_rcept_no = match.group(1)
        dcm_no = match.group(2)
        attachments.append(
            _ViewerAttachmentCandidate(
                attachment=_viewer_attachment(
                    rcept_no,
                    source_rcept_no,
                    dcm_no,
                    page_title,
                ),
                source_receipt_stated=True,
                title_from_selectable=False,
            )
        )
    return tuple(attachments)


def _viewer_attachment(
    rcept_no: str,
    source_rcept_no: str,
    dcm_no: str,
    title: str,
) -> Attachment:
    attachment_name = _attachment_name(rcept_no, source_rcept_no, dcm_no)
    return Attachment(
        attachment_id=f"viewer:{rcept_no}:{attachment_name}",
        rcept_no=rcept_no,
        source_rcept_no=source_rcept_no,
        title=title,
        source="viewer",
        standalone="연결" not in title,
        dcm_no=dcm_no,
    )


def _attachment_name(
    rcept_no: str,
    source_rcept_no: str,
    name: str,
) -> str:
    """Prefix an attachment name only when its source receipt differs."""
    if source_rcept_no == rcept_no:
        return name
    return f"{_EXTENDED_NAME_MARKER}{source_rcept_no}/{name}"


def _zip_warning_details(
    requested_reason: str | None,
    source_reason: str | None = None,
    *,
    source_rcept_nos: tuple[str, ...] = (),
) -> JsonObject:
    """Build safe diagnostic details for ZIP fallback warnings."""
    details: JsonObject = {}
    if requested_reason is not None:
        details["requested_zip_reason"] = requested_reason
    if source_reason is not None:
        details["source_zip_reason"] = source_reason
    if source_rcept_nos:
        details["source_receipt_numbers"] = list(source_rcept_nos)
        details["source_receipt_count"] = len(source_rcept_nos)
    return details


def _viewer_discovery_warning(
    reason: str,
    requested_zip_reason: str | None,
) -> WarningInfo:
    """Report that original-filing discovery could not run."""
    # The requested ZIP remained the primary source, so this is not a fallback.
    details = _zip_warning_details(requested_zip_reason)
    details["viewer_failure_reason"] = reason
    return WarningInfo(
        code=WarningCode.VIEWER_DISCOVERY_SKIPPED,
        message="DART 웹 첨부 탐색을 완료하지 못해 목록이 일부 누락될 수 있습니다.",
        details=details,
    )


def _unrecovered_viewer_attachments(
    viewer_attachments: tuple[Attachment, ...],
    recovered_attachments: tuple[Attachment, ...],
) -> tuple[Attachment, ...]:
    recovered_counts = Counter(
        _report_match_key(attachment) for attachment in recovered_attachments
    )
    unrecovered: list[Attachment] = []
    for attachment in viewer_attachments:
        identity = _report_match_key(attachment)
        if recovered_counts[identity] > 0:
            recovered_counts[identity] -= 1
            continue
        unrecovered.append(attachment)
    return tuple(unrecovered)


def _report_match_key(attachment: Attachment) -> tuple[str, str]:
    """Ignore interim period qualifiers without changing the displayed title."""
    scope = "연결" if "연결" in attachment.title else "별도"
    if "감사보고서" in attachment.title:
        report_kind = "감사보고서"
    elif "검토보고서" in attachment.title:
        report_kind = "검토보고서"
    else:
        report_kind = attachment.title
    return scope, report_kind


def _merge_viewer_attachments(
    groups: tuple[tuple[_ViewerAttachmentCandidate, ...], ...],
) -> tuple[Attachment, ...]:
    attachments_by_dcm: dict[str, _ViewerAttachmentCandidate] = {}
    for group in groups:
        for candidate in group:
            dcm_no = candidate.attachment.dcm_no
            if dcm_no is None:
                continue
            existing = attachments_by_dcm.get(dcm_no)
            if existing is None:
                attachments_by_dcm[dcm_no] = candidate
                continue
            source_candidate = (
                candidate
                if (
                    candidate.source_receipt_stated
                    and not existing.source_receipt_stated
                )
                else existing
            )
            title_candidate = (
                candidate
                if (
                    candidate.title_from_selectable
                    and not existing.title_from_selectable
                )
                else existing
            )
            attachments_by_dcm[dcm_no] = _ViewerAttachmentCandidate(
                attachment=_viewer_attachment(
                    existing.attachment.rcept_no,
                    source_candidate.attachment.source_rcept_no,
                    dcm_no,
                    title_candidate.attachment.title,
                ),
                source_receipt_stated=source_candidate.source_receipt_stated,
                title_from_selectable=title_candidate.title_from_selectable,
            )
    return tuple(
        candidate.attachment for candidate in attachments_by_dcm.values()
    )


def _viewer_report_title(title: str) -> str:
    collapsed = " ".join(title.split())
    consolidated = "연결" in collapsed
    review_report = any(
        suffix in collapsed for suffix in _REVIEW_REPORT_SUFFIXES
    )
    if "분기" in collapsed and review_report:
        base = "분기검토보고서"
    elif "반기" in collapsed and review_report:
        base = "반기검토보고서"
    elif review_report:
        base = "검토보고서"
    elif "감사보고서" in collapsed:
        base = "감사보고서"
    else:
        return collapsed
    return f"{'연결' if consolidated else '별도'}{base}"


def _viewer_report_label(title: str) -> str:
    return _VIEWER_DATE_PREFIX_PATTERN.sub("", title, count=1)


def _is_report_title(title: str) -> bool:
    compacted = compact(title)
    suffix = _REPORT_TITLE_PATTERN.search(compacted)
    if suffix is None:
        return False
    if any(
        compacted.startswith(exclusion)
        for exclusion in _REPORT_TITLE_START_EXCLUSIONS
    ):
        return False
    prefix = compacted[: suffix.start()]
    return not any(
        prefix.endswith(exclusion)
        for exclusion in _REPORT_TITLE_SUFFIX_PREFIX_EXCLUSIONS
    )


def _xml_report_title(content: bytes) -> str | None:
    soup = BeautifulSoup(content, "xml")
    title_nodes = soup.find_all(["TITLE", "title"])
    compacted_titles = tuple(compact(node.get_text()) for node in title_nodes)
    base_title: str | None = None
    report_title_consolidated = False
    for title in compacted_titles:
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
            if compact(candidate) in title:
                base_title = "검토보고서" if "검토" in candidate else "감사보고서"
                report_title_consolidated = "연결" in title
                break
        if base_title is not None:
            break
    if base_title is None:
        return None
    statement_titles = tuple(
        title for title in compacted_titles if "재무제표" in title
    )
    statement_title = next(
        (title for title in statement_titles if "(첨부)" in title),
        None,
    )
    if statement_title is None:
        statement_title = next(
            (title for title in statement_titles if title.endswith("재무제표")),
            None,
        )
    if statement_title is None and statement_titles:
        statement_title = statement_titles[-1]
    if statement_title is not None:
        consolidated = "연결" in statement_title or report_title_consolidated
    else:
        full_text = soup.get_text(" ", strip=True)
        consolidated = full_text.count("연결") > full_text.count("별도")
    return f"{'연결' if consolidated else '별도'}{base_title}"
