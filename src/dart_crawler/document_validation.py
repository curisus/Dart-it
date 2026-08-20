"""Validate raw-source coverage and normalized document table structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from dart_crawler.document_model import BlockKind, DocumentBlock, ParsedDocument
from dart_crawler.result import ErrorCode, Result, error_info


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    """Counts of source-derived cells and merge ranges checked."""

    checked_cell_count: int
    checked_merge_count: int


def validate_document(document: ParsedDocument) -> Result[ValidationSummary]:
    """Reject incomplete source capture or malformed tables before XLSX writing."""
    coverage = document.source_coverage
    if coverage is None:
        return _coverage_failure("source_coverage_missing")
    if not coverage.complete:
        return _coverage_failure(
            "incomplete_source_coverage",
            source_text_token_count=coverage.source_text_token_count,
            captured_text_token_count=coverage.captured_text_token_count,
            source_table_count=coverage.source_table_count,
            captured_table_count=coverage.captured_table_count,
            source_cell_count=coverage.source_cell_count,
            captured_cell_count=coverage.captured_cell_count,
            source_image_count=coverage.source_image_count,
            captured_image_count=coverage.captured_image_count,
        )
    checked_cell_count = 0
    checked_merge_count = 0
    for section_number, section in enumerate(document.sections, start=1):
        for block_number, block in enumerate(section.blocks, start=1):
            if block.kind in {BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.IMAGE}:
                checked_cell_count += 1
                continue
            if block.kind is not BlockKind.TABLE:
                assert_never(block.kind)
            table_validation = _validate_table(block, section_number, block_number)
            if not table_validation.ok or table_validation.data is None:
                return table_validation
            checked_cell_count += table_validation.data.checked_cell_count
            checked_merge_count += table_validation.data.checked_merge_count
    return Result.success(
        ValidationSummary(
            checked_cell_count=checked_cell_count,
            checked_merge_count=checked_merge_count,
        )
    )


def _validate_table(
    block: DocumentBlock,
    section_number: int,
    block_number: int,
) -> Result[ValidationSummary]:
    if not block.rows:
        return _document_failure("empty_table", section_number, block_number)
    width = len(block.rows[0])
    if width == 0 or any(len(row) != width for row in block.rows):
        return _document_failure(
            "non_rectangular_table", section_number, block_number
        )
    occupied: set[tuple[int, int]] = set()
    for start_row, start_column, end_row, end_column in block.merged_ranges:
        if (
            start_row < 1
            or start_column < 1
            or end_row < start_row
            or end_column < start_column
            or end_row > len(block.rows)
            or end_column > width
        ):
            return _document_failure(
                "merge_out_of_bounds", section_number, block_number
            )
        coordinates = {
            (row_number, column_number)
            for row_number in range(start_row, end_row + 1)
            for column_number in range(start_column, end_column + 1)
        }
        if occupied.intersection(coordinates):
            return _document_failure(
                "overlapping_merges", section_number, block_number
            )
        if any(
            block.rows[row_number - 1][column_number - 1]
            for row_number, column_number in coordinates
            if (row_number, column_number) != (start_row, start_column)
        ):
            return _document_failure(
                "merge_contains_secondary_value", section_number, block_number
            )
        occupied.update(coordinates)
    return Result.success(
        ValidationSummary(
            checked_cell_count=len(block.rows) * width,
            checked_merge_count=len(block.merged_ranges),
        )
    )


def _coverage_failure(issue: str, **counts: int) -> Result[ValidationSummary]:
    return Result.failure(
        error_info(
            ErrorCode.VALIDATION_FAILED,
            "DART 원문의 수집 대상 항목이 모두 반영되지 않아 결과를 반환하지 않았습니다.",
            retryable=False,
            details={"issue": issue, **counts},
        ),
        next_action="DART 원문 구조 변경 여부를 확인한 뒤 다시 실행하세요.",
    )


def _document_failure(
    issue: str,
    section_number: int,
    block_number: int,
) -> Result[ValidationSummary]:
    return Result.failure(
        error_info(
            ErrorCode.VALIDATION_FAILED,
            "원문 표 구조 검증에 실패하여 결과를 반환하지 않았습니다.",
            retryable=False,
            details={
                "issue": issue,
                "section_number": section_number,
                "block_number": block_number,
            },
        ),
        next_action="다른 첨부문서를 선택하거나 DART 원문 구조 변경 여부를 확인하세요.",
    )
