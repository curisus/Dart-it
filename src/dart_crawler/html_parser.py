"""HTML-to-document-block parser for DART viewer pages."""

from __future__ import annotations

from collections.abc import Sequence
from html.parser import HTMLParser
from typing import Final

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    ParsedDocument,
    build_document,
)
from dart_crawler.result import ErrorCode, Result, error_info
from dart_crawler.source_coverage import (
    IMAGE_TAGS,
    NON_DISPLAY_TAGS,
    TABLE_CELL_TAGS,
    build_source_coverage,
    cdata_content,
    local_name,
    scan_source,
)
from dart_crawler.table_layout import TableCell, layout_table

_HEADING_TAGS: Final = frozenset(
    {"heading", "title", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_PARAGRAPH_TAGS: Final = frozenset({"p", "paragraph", "text", "img-caption"})


class _HtmlBlockParser(HTMLParser):
    """Small ordered parser that avoids depending on browser layout."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[DocumentBlock] = []
        self._text_tag: str | None = None
        self._text_parts: list[str] = []
        self._table_depth = 0
        self._table_cell_rows: list[tuple[TableCell, ...]] = []
        self._current_cells: list[TableCell] = []
        self._cell_parts: list[str] = []
        self._in_cell = False
        self._cell_colspan = 1
        self._cell_rowspan = 1
        self._non_display_depth = 0
        self._in_image_container = False
        self._image_content_depth = 0
        self._image_file_depth = 0
        self.captured_source_cell_count = 0

    def handle_starttag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
        normalized = local_name(tag)
        if self._start_suppressed(normalized):
            return
        if self._start_image(normalized, attrs):
            return
        if self._start_table_markup(normalized, attrs):
            return
        if normalized in _HEADING_TAGS | _PARAGRAPH_TAGS:
            self._text_tag = normalized
            self._text_parts = []
            return
        if normalized == "br":
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = local_name(tag)
        if self._end_suppressed(normalized):
            return
        if self._table_depth and normalized in TABLE_CELL_TAGS and self._in_cell:
            self._current_cells.append(
                TableCell(
                    text=_clean(self._cell_parts),
                    colspan=self._cell_colspan,
                    rowspan=self._cell_rowspan,
                )
            )
            self._in_cell = False
            self.captured_source_cell_count += 1
            self._cell_colspan = 1
            self._cell_rowspan = 1
            return
        if self._table_depth and normalized == "tr":
            if self._current_cells:
                self._table_cell_rows.append(tuple(self._current_cells))
            return
        if normalized == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0 and self._table_cell_rows:
                rows, merged_ranges = layout_table(self._table_cell_rows)
                self.blocks.append(
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=rows,
                        merged_ranges=merged_ranges,
                    )
                )
            return
        if self._text_tag == normalized:
            text = _clean(self._text_parts)
            if text:
                kind = (
                    BlockKind.HEADING
                    if normalized in _HEADING_TAGS
                    else BlockKind.PARAGRAPH
                )
                self.blocks.append(DocumentBlock(kind, text=text))
            self._text_tag = None
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._non_display_depth or self._image_file_depth:
            return
        if self._in_image_container and self._image_content_depth == 0:
            return
        if self._in_cell or self._text_tag is not None:
            self._append_text(data)
            return
        text = _clean((data,))
        if text:
            self.blocks.append(DocumentBlock(BlockKind.PARAGRAPH, text=text))

    def unknown_decl(self, data: str) -> None:
        content = cdata_content(data)
        if content is not None:
            self.handle_data(content)

    def _append_text(self, value: str) -> None:
        if self._in_cell:
            self._cell_parts.append(value)
        elif self._text_tag is not None:
            self._text_parts.append(value)

    def _start_suppressed(self, normalized: str) -> bool:
        if self._non_display_depth:
            self._non_display_depth += 1
            return True
        if normalized in NON_DISPLAY_TAGS:
            self._non_display_depth = 1
            return True
        return False

    def _end_suppressed(self, normalized: str) -> bool:
        if self._non_display_depth:
            self._non_display_depth -= 1
            return True
        if self._image_file_depth:
            self._image_file_depth -= 1
            return True
        if (
            self._in_image_container
            and normalized == "image"
            and self._image_content_depth == 0
        ):
            self._in_image_container = False
            return True
        if self._in_image_container and self._image_content_depth:
            self._image_content_depth -= 1
        return False

    def _start_image(
        self, normalized: str, attrs: Sequence[tuple[str, str | None]]
    ) -> bool:
        if self._image_file_depth:
            self._image_file_depth += 1
            return True
        if self._in_image_container:
            if normalized == "img":
                self._image_file_depth = 1
                return True
            self._image_content_depth += 1
            return False
        if normalized not in IMAGE_TAGS:
            return False
        attributes = dict(attrs)
        self.blocks.append(
            DocumentBlock(BlockKind.IMAGE, image_source=attributes.get("src"))
        )
        if normalized == "image":
            self._in_image_container = True
        elif attributes.get("src") is None:
            self._image_file_depth = 1
        return True

    def _start_table_markup(
        self, normalized: str, attrs: Sequence[tuple[str, str | None]]
    ) -> bool:
        if normalized == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_cell_rows = []
            return True
        if not self._table_depth:
            return False
        if normalized == "tr":
            self._current_cells = []
            return True
        if normalized not in TABLE_CELL_TAGS:
            return False
        attributes = dict(attrs)
        self._in_cell = True
        self._cell_parts = []
        self._cell_colspan = _positive_span(attributes.get("colspan"))
        self._cell_rowspan = _positive_span(attributes.get("rowspan"))
        return True


def parse_html_document(
    content: bytes,
    *,
    source_type: str = "html",
) -> Result[ParsedDocument]:
    """Parse a DART HTML page into the common document structure."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return Result.failure(
            error_info(
                ErrorCode.PARSE_FAILED,
                "HTML 문자를 해석할 수 없습니다.",
                retryable=False,
            )
        )
    parser = _HtmlBlockParser()
    expectation = scan_source(text)
    parser.feed(text)
    parser.close()
    if not parser.blocks:
        return Result.failure(
            error_info(
                ErrorCode.UPSTREAM_LAYOUT_CHANGED,
                "HTML 문서에서 변환 가능한 구역을 찾지 못했습니다.",
                retryable=False,
            )
        )
    coverage = build_source_coverage(
        expectation,
        parser.blocks,
        parser.captured_source_cell_count,
    )
    return Result.success(
        build_document(
            parser.blocks,
            content=content,
            source_type=source_type,
            source_coverage=coverage,
        )
    )


def _clean(parts: Sequence[str]) -> str:
    return " ".join(" ".join(parts).split())


def _positive_span(value: str | None) -> int:
    try:
        return max(1, int(value or "1"))
    except ValueError:
        return 1
