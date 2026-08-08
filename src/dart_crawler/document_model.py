"""Common ordered document blocks used by XML, HTML, and XLSX adapters."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final


@unique
class BlockKind(StrEnum):
    """Block types preserved from a source document."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"


@unique
class SectionKind(StrEnum):
    """Workbook categories inferred from section titles."""

    OPINION = "opinion"
    BALANCE_SHEET = "balance_sheet"
    INCOME = "income"
    EQUITY = "equity"
    CASH_FLOW = "cash_flow"
    NOTE = "note"
    OTHER = "other"


_STATEMENT_KINDS: Final = frozenset(
    {
        SectionKind.BALANCE_SHEET,
        SectionKind.INCOME,
        SectionKind.EQUITY,
        SectionKind.CASH_FLOW,
    }
)


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
    for block in blocks:
        within_note = classify_section(current_title) is SectionKind.NOTE
        inferred_title = _infer_table_title(block)
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
    compact_title = "".join(title.split())
    if "재무상태표" in compact_title:
        return SectionKind.BALANCE_SHEET
    if "손익" in compact_title or "포괄손익" in compact_title:
        return SectionKind.INCOME
    if "자본변동" in compact_title:
        return SectionKind.EQUITY
    if "현금흐름" in compact_title:
        return SectionKind.CASH_FLOW
    if "주석" in compact_title:
        return SectionKind.NOTE
    if (
        "감사의견" in compact_title
        or "검토의견" in compact_title
        or "감사보고서" in compact_title
    ):
        return SectionKind.OPINION
    return SectionKind.OTHER


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
    return within_note and kind in _STATEMENT_KINDS and kind in seen_kinds


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


def _infer_table_title(block: DocumentBlock) -> str | None:
    if block.kind is not BlockKind.TABLE:
        return None
    candidates = (
        "재무상태표",
        "손익 및 포괄손익계산서",
        "손익계산서",
        "포괄손익계산서",
        "자본변동표",
        "현금흐름표",
    )
    for row in block.rows[:3]:
        text = "".join(" ".join(row).split())
        for candidate in candidates:
            if candidate in text:
                return candidate
    return None


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
