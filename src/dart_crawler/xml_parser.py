"""XML-to-document-block parser for OpenDART report files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defusedxml import ElementTree

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    ParsedDocument,
    build_document,
)
from dart_crawler.html_parser import parse_html_document
from dart_crawler.result import (
    ErrorCode,
    Result,
    WarningCode,
    WarningInfo,
    error_info,
)


def parse_xml_document(content: bytes) -> Result[ParsedDocument]:
    """Parse ordered headings, paragraphs, tables, and image placeholders."""
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, UnicodeDecodeError):
        fallback = parse_html_document(content, source_type="xml")
        if fallback.ok and fallback.data is not None:
            return Result.success(
                fallback.data,
                warnings=(
                    WarningInfo(
                        code=WarningCode.FALLBACK_SOURCE_USED,
                        message="엄격한 XML 해석에 실패해 안전한 HTML 호환 파서를 사용했습니다.",
                    ),
                ),
            )
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "XML 문서를 해석할 수 없습니다.",
                retryable=False,
            ),
            next_action="원문 XML이 손상되었거나 구조가 변경되었는지 확인하세요.",
        )
    blocks: list[DocumentBlock] = []
    _walk(root, blocks)
    if not blocks:
        return Result.failure(
            error_info(
                ErrorCode.UPSTREAM_LAYOUT_CHANGED,
                "XML 문서에서 변환 가능한 구역을 찾지 못했습니다.",
                retryable=False,
            ),
            next_action="DART XML 구조 변경 여부를 확인하세요.",
        )
    return Result.success(build_document(blocks, content=content, source_type="xml"))


def _walk(element: Element, blocks: list[DocumentBlock]) -> None:
    tag = _local_name(element.tag)
    if tag in {"heading", "title", "h1", "h2", "h3", "h4", "h5", "h6"}:
        text = _text(element)
        if text:
            blocks.append(DocumentBlock(BlockKind.HEADING, text=text))
        return
    if tag in {"p", "paragraph", "text"}:
        text = _text(element)
        if text:
            blocks.append(DocumentBlock(BlockKind.PARAGRAPH, text=text))
        return
    if tag == "table":
        rows, merged_ranges = _table_rows(element)
        if rows:
            blocks.append(
                DocumentBlock(
                    BlockKind.TABLE,
                    rows=rows,
                    merged_ranges=merged_ranges,
                )
            )
        return
    if tag in {"img", "image"}:
        blocks.append(
            DocumentBlock(BlockKind.IMAGE, image_source=element.attrib.get("src"))
        )
        return
    for child in element:
        _walk(child, blocks)


def _table_rows(
    table: Element,
) -> tuple[
    tuple[tuple[str, ...], ...],
    tuple[tuple[int, int, int, int], ...],
]:
    rows: list[tuple[str, ...]] = []
    merges: list[tuple[int, int, int, int]] = []
    for row in table.iter():
        if _local_name(row.tag) != "tr":
            continue
        values: list[str] = []
        for cell in row:
            if _local_name(cell.tag) not in {"td", "th", "cell"}:
                continue
            start_column = len(values) + 1
            try:
                colspan = max(1, int(cell.attrib.get("colspan", "1") or "1"))
            except ValueError:
                colspan = 1
            values.append(_text(cell))
            values.extend("" for _ in range(colspan - 1))
            if colspan > 1:
                row_number = len(rows) + 1
                merges.append(
                    (row_number, start_column, row_number, start_column + colspan - 1)
                )
        cells = tuple(values)
        if cells:
            rows.append(cells)
    return tuple(rows), tuple(merges)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1].casefold()


def _text(element: Element) -> str:
    return " ".join(" ".join(element.itertext()).split())
