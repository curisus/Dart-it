"""Independent source inventory for non-image collection verification."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final, assert_never

from dart_crawler.document_model import BlockKind, DocumentBlock, SourceCoverage

TABLE_CELL_TAGS: Final = frozenset({"td", "th", "te", "tu", "cell"})
IMAGE_TAGS: Final = frozenset({"img", "image"})
NON_DISPLAY_TAGS: Final = frozenset(
    {"extraction", "formula-version", "script", "style"}
)


@dataclass(frozen=True, slots=True)
class SourceExpectation:
    """Visible source inventory produced independently from document blocks."""

    text_tokens: tuple[str, ...]
    table_count: int
    cell_count: int
    image_count: int


class _SourceScanner(HTMLParser):
    """Mutable streaming accumulator for untrusted source markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_tokens: list[str] = []
        self.table_count = 0
        self.cell_count = 0
        self.image_count = 0
        self._suppressed_depth = 0
        self._in_image_container = False
        self._image_content_depth = 0
        self._image_file_depth = 0

    def handle_starttag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
        normalized = local_name(tag)
        if self._suppressed_depth:
            self._suppressed_depth += 1
            return
        if normalized in NON_DISPLAY_TAGS:
            self._suppressed_depth = 1
            return
        if self._start_image_markup(normalized, attrs):
            return
        if normalized == "table":
            self.table_count += 1
        if normalized in TABLE_CELL_TAGS:
            self.cell_count += 1

    def handle_endtag(self, tag: str) -> None:
        normalized = local_name(tag)
        if self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        if self._image_file_depth:
            self._image_file_depth -= 1
            return
        if (
            self._in_image_container
            and normalized == "image"
            and self._image_content_depth == 0
        ):
            self._in_image_container = False
            return
        if self._in_image_container and self._image_content_depth:
            self._image_content_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth or self._image_file_depth:
            return
        if self._in_image_container and self._image_content_depth == 0:
            return
        self.text_tokens.extend(data.split())

    def unknown_decl(self, data: str) -> None:
        content = cdata_content(data)
        if content is not None:
            self.handle_data(content)

    def _start_image_markup(
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
        if normalized == "image":
            self.image_count += 1
            self._in_image_container = True
            return True
        if normalized != "img":
            return False
        self.image_count += 1
        if dict(attrs).get("src") is None:
            self._image_file_depth = 1
        return True


def scan_source(text: str) -> SourceExpectation:
    """Inventory source text, tables, cells, and images before conversion."""
    scanner = _SourceScanner()
    scanner.feed(text)
    scanner.close()
    return SourceExpectation(
        text_tokens=tuple(scanner.text_tokens),
        table_count=scanner.table_count,
        cell_count=scanner.cell_count,
        image_count=scanner.image_count,
    )


def build_source_coverage(
    expectation: SourceExpectation,
    blocks: Sequence[DocumentBlock],
    captured_source_cell_count: int,
) -> SourceCoverage:
    """Compare the independent source inventory with normalized blocks."""
    captured_tokens: list[str] = []
    captured_table_count = 0
    captured_image_count = 0
    for block in blocks:
        match block.kind:
            case BlockKind.HEADING | BlockKind.PARAGRAPH:
                captured_tokens.extend(block.text.split())
            case BlockKind.TABLE:
                captured_table_count += 1
                for row in block.rows:
                    for value in row:
                        captured_tokens.extend(value.split())
            case BlockKind.IMAGE:
                captured_image_count += 1
            case unreachable:
                assert_never(unreachable)
    return SourceCoverage(
        source_text_token_count=len(expectation.text_tokens),
        captured_text_token_count=len(captured_tokens),
        source_text_sha256=_token_sha256(expectation.text_tokens),
        captured_text_sha256=_token_sha256(captured_tokens),
        source_table_count=expectation.table_count,
        captured_table_count=captured_table_count,
        source_cell_count=expectation.cell_count,
        captured_cell_count=captured_source_cell_count,
        source_image_count=expectation.image_count,
        captured_image_count=captured_image_count,
    )


def local_name(tag: str) -> str:
    """Normalize HTML and namespaced XML tag names."""
    return tag.rsplit(":", maxsplit=1)[-1].casefold()


def cdata_content(declaration: str) -> str | None:
    prefix = "CDATA["
    if declaration.startswith(prefix):
        return declaration[len(prefix) :]
    return None


def source_coverage_metadata(coverage: SourceCoverage) -> dict[str, str]:
    return {
        "source_coverage_status": "passed" if coverage.complete else "failed",
        "source_text_token_count": str(coverage.source_text_token_count),
        "captured_text_token_count": str(coverage.captured_text_token_count),
        "source_table_count": str(coverage.source_table_count),
        "captured_table_count": str(coverage.captured_table_count),
        "source_cell_count": str(coverage.source_cell_count),
        "captured_cell_count": str(coverage.captured_cell_count),
        "source_image_count": str(coverage.source_image_count),
        "captured_image_count": str(coverage.captured_image_count),
    }


def _token_sha256(tokens: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for token in tokens:
        encoded = token.encode()
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()
