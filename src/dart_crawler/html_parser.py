"""HTML-to-document-block parser for DART viewer pages."""

from __future__ import annotations

from collections.abc import Sequence
from html.parser import HTMLParser

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    ParsedDocument,
    build_document,
)
from dart_crawler.result import ErrorCode, Result, error_info


class _HtmlBlockParser(HTMLParser):
    """Small ordered parser that avoids depending on browser layout."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[DocumentBlock] = []
        self._text_tag: str | None = None
        self._text_parts: list[str] = []
        self._table_depth = 0
        self._table_rows: list[tuple[str, ...]] = []
        self._table_merges: list[tuple[int, int, int, int]] = []
        self._current_row: list[str] = []
        self._cell_parts: list[str] = []
        self._in_cell = False
        self._cell_colspan = 1

    def handle_starttag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
        normalized = tag.casefold()
        if normalized == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_rows = []
                self._table_merges = []
            return
        if self._table_depth and normalized == "tr":
            self._current_row = []
            return
        if self._table_depth and normalized in {"td", "th", "te"}:
            self._in_cell = True
            self._cell_parts = []
            attributes = dict(attrs)
            try:
                self._cell_colspan = max(1, int(attributes.get("colspan", "1") or "1"))
            except ValueError:
                self._cell_colspan = 1
            return
        if normalized in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "title"}:
            self._text_tag = normalized
            self._text_parts = []
            return
        if normalized == "img":
            attributes = dict(attrs)
            self.blocks.append(
                DocumentBlock(BlockKind.IMAGE, image_source=attributes.get("src"))
            )
        if normalized == "br":
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if self._table_depth and normalized in {"td", "th", "te"} and self._in_cell:
            start_column = len(self._current_row) + 1
            self._current_row.append(_clean(self._cell_parts))
            self._current_row.extend("" for _ in range(self._cell_colspan - 1))
            if self._cell_colspan > 1:
                row_number = len(self._table_rows) + 1
                self._table_merges.append(
                    (
                        row_number,
                        start_column,
                        row_number,
                        start_column + self._cell_colspan - 1,
                    )
                )
            self._in_cell = False
            self._cell_colspan = 1
            return
        if self._table_depth and normalized == "tr":
            if self._current_row:
                self._table_rows.append(tuple(self._current_row))
            return
        if normalized == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0 and self._table_rows:
                self.blocks.append(
                    DocumentBlock(
                        BlockKind.TABLE,
                        rows=tuple(self._table_rows),
                        merged_ranges=tuple(self._table_merges),
                    )
                )
            return
        if self._text_tag == normalized:
            text = _clean(self._text_parts)
            if text:
                kind = (
                    BlockKind.HEADING
                    if normalized.startswith("h") or normalized == "title"
                    else BlockKind.PARAGRAPH
                )
                self.blocks.append(DocumentBlock(kind, text=text))
            self._text_tag = None
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def _append_text(self, value: str) -> None:
        if self._in_cell:
            self._cell_parts.append(value)
        elif self._text_tag is not None:
            self._text_parts.append(value)


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
    return Result.success(
        build_document(parser.blocks, content=content, source_type=source_type)
    )


def _clean(parts: Sequence[str]) -> str:
    return " ".join(" ".join(parts).split())
