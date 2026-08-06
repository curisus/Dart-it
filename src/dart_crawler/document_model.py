"""Common ordered document blocks used by XML, HTML, and XLSX adapters."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum, unique


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
    for block in blocks:
        inferred_title = _infer_table_title(block)
        if (
            inferred_title is not None
            and current_blocks
            and (
                classify_section(current_title) is SectionKind.OTHER
                or classify_section(inferred_title)
                is not classify_section(current_title)
            )
        ):
            sections.append(
                DocumentSection(
                    title=current_title,
                    kind=classify_section(current_title),
                    blocks=tuple(current_blocks),
                )
            )
            current_blocks = []
            current_title = inferred_title
        if block.kind is BlockKind.HEADING and block.text.strip() and current_blocks:
            sections.append(
                DocumentSection(
                    title=current_title,
                    kind=classify_section(current_title),
                    blocks=tuple(current_blocks),
                )
            )
            current_blocks = []
        if block.kind is BlockKind.HEADING and block.text.strip():
            current_title = block.text.strip()
        current_blocks.append(block)
    if current_blocks:
        sections.append(
            DocumentSection(
                title=current_title,
                kind=classify_section(current_title),
                blocks=tuple(current_blocks),
            )
        )
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
