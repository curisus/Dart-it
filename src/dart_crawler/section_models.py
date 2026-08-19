"""Section identity, summaries, and selection shared by data and Excel paths."""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
)
from dart_crawler.result import ErrorCode, JsonObject, Result, error_info
from dart_crawler.statement_lexicon import statement_kinds

# One response must stay small enough for a client context window. Selections
# above the limit fail: truncating would return data no cross-check can verify.
MAX_RESPONSE_CELLS: Final = 20_000
# Tables and narrative are measured separately because a notes-only or
# opinion-only selection holds no cells at all, so the cell limit never sees it.
# A whole real report stays far below this bound — the 47-section 삼성전자 audit
# report carries 29,611 narrative characters in total — so no honest request is
# refused, while the selections that produce the 159-533KB responses the design
# calls too big are split up.
MAX_RESPONSE_TEXT_CHARS: Final = 200_000
STATEMENTS_ALIAS: Final = "statements"

_SECTION_ID_PATTERN: Final = re.compile(r"^s(\d{3,})-([a-z_]+)$")
_SECTION_KIND_VALUES: Final[frozenset[str]] = frozenset(
    kind.value for kind in SectionKind
)
_SUPPORTED_KIND_VALUES: Final = (
    *(kind.value for kind in SectionKind),
    STATEMENTS_ALIAS,
)
_CORE_STATEMENT_LABELS: Final[tuple[tuple[SectionKind, str], ...]] = (
    (SectionKind.BALANCE_SHEET, "재무상태표"),
    (SectionKind.INCOME, "손익·포괄손익"),
    (SectionKind.EQUITY, "자본변동표"),
    (SectionKind.CASH_FLOW, "현금흐름표"),
)
_RETRY_LISTING_NEXT_ACTION: Final = (
    "list_report_sections를 다시 호출해 최신 목차를 확인하세요."
)
_SPLIT_SELECTION_NEXT_ACTION: Final = "구역을 나누어 여러 번 호출하세요."


class TableData(BaseModel):
    """One source table kept as text cells with its merge ranges."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[tuple[str, ...], ...]
    merged_ranges: tuple[tuple[int, int, int, int], ...] = ()


class SectionBlock(BaseModel):
    """One ordered block of a section, in source order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: BlockKind
    text: str = ""
    table: TableData | None = None
    image_source: str | None = None


class SectionSummary(BaseModel):
    """Table-of-contents entry describing one section without its content.

    ``cell_count`` prices the section's tables and ``text_char_count`` prices
    everything else: it is the character count of the text carried by the
    headings, paragraphs, and images, and deliberately excludes table cells so
    that the two numbers never charge the same content twice.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str
    title: str
    kind: SectionKind
    block_count: int
    table_count: int
    cell_count: int
    text_char_count: int
    has_image: bool


class ReportSectionList(BaseModel):
    """Section table of contents returned for one parsed attachment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rcept_no: str
    attachment_id: str
    report_title: str | None
    source_type: str
    source_sha256: str
    parser_version: str
    coverage_complete: bool
    section_count: int
    total_cell_count: int
    total_text_char_count: int
    sections: tuple[SectionSummary, ...]


class SectionData(BaseModel):
    """One selected section with every block it holds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str
    title: str
    kind: SectionKind
    blocks: tuple[SectionBlock, ...]


class ReportSectionData(BaseModel):
    """Selected section content returned for one parsed attachment.

    The two counts price the response on the same two axes the table of
    contents uses, so a caller can reconcile what it asked for against what it
    received without walking the blocks itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rcept_no: str
    attachment_id: str
    source_sha256: str
    parser_version: str
    returned_cell_count: int
    returned_text_char_count: int
    sections: tuple[SectionData, ...]


def section_id(index: int, kind: SectionKind) -> str:
    """Return the identifier of the section at a source-order index."""
    return f"s{index + 1:03d}-{kind.value}"


def summarize_sections(document: ParsedDocument) -> tuple[SectionSummary, ...]:
    """Describe every section in source order without copying its content."""
    return tuple(
        SectionSummary(
            section_id=section_id(index, section.kind),
            title=section.title,
            kind=section.kind,
            block_count=len(section.blocks),
            table_count=sum(
                1 for block in section.blocks if block.kind is BlockKind.TABLE
            ),
            cell_count=_section_cell_count(section),
            text_char_count=_section_text_char_count(section),
            has_image=any(
                block.kind is BlockKind.IMAGE for block in section.blocks
            ),
        )
        for index, section in enumerate(document.sections)
    )


def returned_cell_count(sections: tuple[SectionData, ...]) -> int:
    """Count every table grid slot carried by the selected sections."""
    return sum(
        _row_cell_count(block.table.rows)
        for section in sections
        for block in section.blocks
        if block.table is not None
    )


def returned_text_char_count(sections: tuple[SectionData, ...]) -> int:
    """Count the characters the selected sections carry outside their tables."""
    return sum(
        len(block.text)
        for section in sections
        for block in section.blocks
        if block.kind is not BlockKind.TABLE
    )


def select_sections(
    document: ParsedDocument,
    section_ids: tuple[str, ...],
    section_kinds: tuple[str, ...],
) -> Result[tuple[SectionData, ...]]:
    """Return the union of the sections named by identifier and by kind."""
    if not section_ids and not section_kinds:
        return _invalid_input(
            "section_ids 또는 section_kinds 중 하나 이상을 지정해야 합니다.",
            next_action=(
                "list_report_sections가 돌려준 section_id를 고르거나 "
                "section_kinds에 statements를 지정하세요."
            ),
        )
    malformed = tuple(value for value in section_ids if not _is_section_id(value))
    if malformed:
        return _invalid_input(
            "section_id 형식이 올바르지 않습니다.",
            details={"invalid_section_ids": list(malformed)},
            next_action=_RETRY_LISTING_NEXT_ACTION,
        )
    unknown = tuple(
        value for value in section_kinds if value not in _SUPPORTED_KIND_VALUES
    )
    if unknown:
        return _invalid_input(
            "지원하지 않는 section_kinds 값입니다.",
            details={
                "unknown_section_kinds": list(unknown),
                "supported_section_kinds": list(_SUPPORTED_KIND_VALUES),
            },
            next_action="section_kinds에는 statements 별칭이나 목차의 kind 값을 지정하세요.",
        )
    wanted_ids = frozenset(section_ids)
    wanted_kinds = _expand_kinds(section_kinds)
    selected = tuple(
        _section_data(identifier, section)
        for identifier, section in _identified_sections(document)
        if identifier in wanted_ids or section.kind in wanted_kinds
    )
    if not selected:
        return Result.failure(
            error_info(
                ErrorCode.NOT_FOUND,
                "선택한 구역을 이 첨부문서에서 찾지 못했습니다.",
                retryable=False,
                details={
                    "requested_section_ids": list(section_ids),
                    "requested_section_kinds": list(section_kinds),
                },
            ),
            next_action=_RETRY_LISTING_NEXT_ACTION,
        )
    oversized = _oversized_selection(selected)
    if oversized is not None:
        return oversized
    return Result.success(selected)


def missing_core_sections(document: ParsedDocument) -> tuple[str, ...]:
    """Return the core statement labels that no table-bearing section covers."""
    missing = []
    for kind, label in _CORE_STATEMENT_LABELS:
        sections = [section for section in document.sections if section.kind is kind]
        if not sections or not any(
            block.kind is BlockKind.TABLE
            for section in sections
            for block in section.blocks
        ):
            missing.append(label)
    return tuple(missing)


def _identified_sections(
    document: ParsedDocument,
) -> tuple[tuple[str, DocumentSection], ...]:
    return tuple(
        (section_id(index, section.kind), section)
        for index, section in enumerate(document.sections)
    )


def _section_data(identifier: str, section: DocumentSection) -> SectionData:
    return SectionData(
        section_id=identifier,
        title=section.title,
        kind=section.kind,
        blocks=tuple(_section_block(block) for block in section.blocks),
    )


def _section_block(block: DocumentBlock) -> SectionBlock:
    table = (
        TableData(rows=block.rows, merged_ranges=block.merged_ranges)
        if block.kind is BlockKind.TABLE
        else None
    )
    return SectionBlock(
        kind=block.kind,
        text=block.text,
        table=table,
        image_source=block.image_source,
    )


def _oversized_selection(
    selected: tuple[SectionData, ...],
) -> Result[tuple[SectionData, ...]] | None:
    """Reject a selection that outgrows either response limit.

    Both dimensions are named when both are exceeded, so a caller who splits
    only on cell count is not rejected a second time on narrative length.
    """
    selected_cell_count = returned_cell_count(selected)
    selected_text_char_count = returned_text_char_count(selected)
    over_text = selected_text_char_count > MAX_RESPONSE_TEXT_CHARS
    if selected_cell_count > MAX_RESPONSE_CELLS:
        details: JsonObject = {
            "selected_cell_count": selected_cell_count,
            "limit": MAX_RESPONSE_CELLS,
        }
        if over_text:
            details["selected_text_char_count"] = selected_text_char_count
            details["text_char_limit"] = MAX_RESPONSE_TEXT_CHARS
        return _invalid_input(
            "선택한 구역의 셀 수가 한 번에 반환할 수 있는 한도를 초과했습니다.",
            details=details,
            next_action=_SPLIT_SELECTION_NEXT_ACTION,
        )
    if over_text:
        return _invalid_input(
            "선택한 구역의 서술 텍스트 분량이 한 번에 반환할 수 있는 한도를 초과했습니다.",
            details={
                "selected_text_char_count": selected_text_char_count,
                "limit": MAX_RESPONSE_TEXT_CHARS,
            },
            next_action=_SPLIT_SELECTION_NEXT_ACTION,
        )
    return None


def _section_cell_count(section: DocumentSection) -> int:
    return sum(
        _row_cell_count(block.rows)
        for block in section.blocks
        if block.kind is BlockKind.TABLE
    )


def _section_text_char_count(section: DocumentSection) -> int:
    return sum(
        len(block.text)
        for block in section.blocks
        if block.kind is not BlockKind.TABLE
    )


def _row_cell_count(rows: tuple[tuple[str, ...], ...]) -> int:
    return sum(len(row) for row in rows)


def _is_section_id(value: str) -> bool:
    match = _SECTION_ID_PATTERN.match(value)
    return match is not None and match.group(2) in _SECTION_KIND_VALUES


def _expand_kinds(values: tuple[str, ...]) -> frozenset[SectionKind]:
    kinds: set[SectionKind] = set()
    for value in values:
        if value == STATEMENTS_ALIAS:
            kinds.update(statement_kinds)
            continue
        kinds.add(SectionKind(value))
    return frozenset(kinds)


def _invalid_input(
    message: str,
    *,
    details: JsonObject | None = None,
    next_action: str,
) -> Result[tuple[SectionData, ...]]:
    return Result.failure(
        error_info(
            ErrorCode.INVALID_INPUT,
            message,
            retryable=False,
            details=details,
        ),
        next_action=next_action,
    )
