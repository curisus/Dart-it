"""Select the common XML or HTML parser for one attachment."""

from __future__ import annotations

from dart_crawler.document_model import ParsedDocument
from dart_crawler.html_parser import parse_html_document
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.xml_parser import parse_xml_document


def parse_attachment(content: bytes, attachment_id: str) -> Result[ParsedDocument]:
    """Parse an attachment according to its fixed source identifier."""
    if attachment_id.startswith("opendart:") and attachment_id.casefold().endswith(
        ".xml"
    ):
        return parse_xml_document(content)
    if attachment_id.startswith("viewer:") or attachment_id.casefold().endswith(
        ".html"
    ):
        return parse_html_document(content)
    return Result.failure(
        error_info(
            ErrorCode.INVALID_INPUT,
            "첨부 식별자에서 문서 형식을 확인할 수 없습니다.",
            retryable=False,
        )
    )
