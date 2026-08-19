"""Common ordered document blocks used by XML, HTML, and XLSX adapters."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum, unique
from dart_crawler.statement_lexicon import SectionKind as SectionKind  # noqa: PLC0414
from dart_crawler.statement_lexicon import (
    classify,
    statement_kinds,
    statement_title_in_rows,
    statement_title_of_line,
)


@unique
class BlockKind(StrEnum):
    """Block types preserved from a source document."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    """One ordered paragraph, table, heading, or image placeholder."""

    kind: BlockKind
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    image_source: str | None = None
    merged_ranges: tuple[tuple[int, int, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """A source-order section that becomes one workbook sheet."""

    title: str
    kind: SectionKind
    blocks: tuple[DocumentBlock, ...]


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    """Source-to-document counts and fingerprints for non-image content."""

    source_text_token_count: int
    captured_text_token_count: int
    source_text_sha256: str
    captured_text_sha256: str
    source_table_count: int
    captured_table_count: int
    source_cell_count: int
    captured_cell_count: int
    source_image_count: int
    captured_image_count: int

    @property
    def complete(self) -> bool:
        """Return whether every source item reached the normalized document."""
        return (
            self.source_text_token_count == self.captured_text_token_count
            and self.source_text_sha256 == self.captured_text_sha256
            and self.source_table_count == self.captured_table_count
            and self.source_cell_count == self.captured_cell_count
            and self.source_image_count == self.captured_image_count
        )


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalized document with source metadata."""

    sections: tuple[DocumentSection, ...]
    source_sha256: str
    source_type: str
    report_title: str | None = None
    report_date: str | None = None
    source_coverage: SourceCoverage | None = None


def build_document(
    blocks: Iterable[DocumentBlock],
    *,
    content: bytes,
    source_type: str,
    source_coverage: SourceCoverage | None = None,
) -> ParsedDocument:
    """Group ordered blocks into title-driven sections."""
    sections: list[DocumentSection] = []
    current_title = "본문"
    current_blocks: list[DocumentBlock] = []
    seen_kinds: set[SectionKind] = set()
    ordered = tuple(blocks)
    for position, block in enumerate(ordered):
        within_note = classify_section(current_title) is SectionKind.NOTE
        inferred_title = _infer_section_title(block, ordered, position + 1)
        if (
            inferred_title is not None
            and current_blocks
            and not _stays_inside_note(
                inferred_title, seen_kinds, within_note=within_note
            )
            and (
                classify_section(current_title) is SectionKind.OTHER
                or classify_section(inferred_title)
                is not classify_section(current_title)
            )
        ):
            _close_section(sections, seen_kinds, current_title, current_blocks)
            current_blocks = []
            current_title = inferred_title
        heading_title = _section_heading_title(
            block, seen_kinds, within_note=within_note
        )
        if heading_title is not None:
            if current_blocks:
                _close_section(sections, seen_kinds, current_title, current_blocks)
                current_blocks = []
            current_title = heading_title
        current_blocks.append(block)
    if current_blocks:
        _close_section(sections, seen_kinds, current_title, current_blocks)
    sections = _split_note_sections(sections)
    return ParsedDocument(
        sections=tuple(sections),
        source_sha256=hashlib.sha256(content).hexdigest(),
        source_type=source_type,
        report_title=sections[0].title if sections else None,
        source_coverage=source_coverage,
    )


def classify_section(title: str) -> SectionKind:
    """Classify a section by stable DART report terminology."""
    return classify(title)


def _close_section(
    sections: list[DocumentSection],
    seen_kinds: set[SectionKind],
    title: str,
    blocks: list[DocumentBlock],
) -> None:
    """Append a finished section and record kinds that carry a real table.

    Only table-bearing sections count, matching what core-statement checks
    require, so a title alone can never mask a statement that is still coming.
    """
    section = DocumentSection(
        title=title,
        kind=classify_section(title),
        blocks=tuple(blocks),
    )
    sections.append(section)
    if any(block.kind is BlockKind.TABLE for block in section.blocks):
        seen_kinds.add(section.kind)


def _stays_inside_note(
    title: str,
    seen_kinds: set[SectionKind],
    *,
    within_note: bool,
) -> bool:
    """Whether a statement title repeats inside a note instead of opening a sheet.

    Suppression needs an earlier section of the same kind that already holds a
    table, so it can never hide a core statement; only a later repeat inside a
    note is folded back into that note.
    """
    kind = classify_section(title)
    return within_note and kind in statement_kinds and kind in seen_kinds


def _section_heading_title(
    block: DocumentBlock,
    seen_kinds: set[SectionKind],
    *,
    within_note: bool,
) -> str | None:
    """Return the title a heading starts, or None when it stays inside a note."""
    if block.kind is not BlockKind.HEADING:
        return None
    title = block.text.strip()
    if not title or _stays_inside_note(title, seen_kinds, within_note=within_note):
        return None
    return title


def _infer_section_title(
    block: DocumentBlock,
    ordered: Sequence[DocumentBlock],
    next_position: int,
) -> str | None:
    """Return the statement a table header or a standalone title line announces."""
    if block.kind is BlockKind.TABLE:
        return _title_from_rows(block.rows)
    if block.kind is not BlockKind.PARAGRAPH:
        return None
    title = statement_title_of_line(block.text)
    if title is None or not _announces_table(ordered, next_position):
        return None
    return title


def _announces_table(ordered: Sequence[DocumentBlock], start: int) -> bool:
    """Whether a title line is followed by the statement table it names.

    Blank lines and caption lines such as the period, the company, or the unit
    may sit in between. Another title line means the document is listing
    statements, as a table of contents does, and names no table.
    """
    for position in range(start, len(ordered)):
        block = ordered[position]
        if block.kind is not BlockKind.PARAGRAPH:
            return block.kind is BlockKind.TABLE
        if statement_title_of_line(block.text) is not None:
            return False
    return False


def _title_from_rows(rows: tuple[tuple[str, ...], ...]) -> str | None:
    return statement_title_in_rows(rows)


def _split_note_sections(
    sections: list[DocumentSection],
) -> list[DocumentSection]:
    result: list[DocumentSection] = []
    note_pattern = re.compile(r"^(\d+)\.\s")
    for section in sections:
        if section.kind is not SectionKind.NOTE:
            result.append(section)
            continue
        current_title = section.title
        current_blocks: list[DocumentBlock] = []
        for block in section.blocks:
            text = block.text if block.kind is not BlockKind.TABLE else ""
            match = note_pattern.match(text.lstrip())
            if match is not None:
                if current_blocks:
                    result.append(
                        DocumentSection(
                            title=current_title,
                            kind=SectionKind.NOTE,
                            blocks=tuple(current_blocks),
                        )
                    )
                current_title = f"주석 {match.group(1)}"
                current_blocks = []
            current_blocks.append(block)
        if current_blocks:
            result.append(
                DocumentSection(
                    title=current_title,
                    kind=SectionKind.NOTE,
                    blocks=tuple(current_blocks),
                )
            )
    return result
