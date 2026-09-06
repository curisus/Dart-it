"""XML-to-document-block parser for OpenDART report files."""

from __future__ import annotations

from defusedxml import ElementTree

from dart_crawler.document_model import ParsedDocument
from dart_crawler.fallback_axis import FALLBACK_AXIS_KEY, FallbackAxis
from dart_crawler.html_parser import parse_html_document
from dart_crawler.result import (
    ErrorCode,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)


def parse_xml_document(content: bytes) -> Result[ParsedDocument]:
    """Validate XML safety and apply the shared ordered markup parser."""
    warnings: tuple[WarningInfo, ...] = ()
    try:
        ElementTree.fromstring(content)
    except (ElementTree.ParseError, UnicodeDecodeError):
        warnings = (
            WarningInfo(
                code=WarningCode.FALLBACK_SOURCE_USED,
                message="엄격한 XML 해석에 실패해 안전한 HTML 호환 파서를 사용했습니다.",
                details={FALLBACK_AXIS_KEY: FallbackAxis.PARSER.value},
            ),
        )
    parsed = parse_html_document(content, source_type="xml")
    if not parsed.ok or parsed.data is None:
        return Result.failure(
            parsed.error
            if parsed.error is not None
            else error_info(
                ErrorCode.PARSE_FAILED, "XML 문서를 해석할 수 없습니다.", retryable=False
            ),
            warnings=warnings + parsed.warnings,
            next_action="원문 XML이 손상되었거나 구조가 변경되었는지 확인하세요.",
        )
    return Result.success(
        parsed.data,
        warnings=warnings + parsed.warnings,
        next_action=parsed.next_action,
    )
