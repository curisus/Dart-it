from dart_crawler.document_model import BlockKind
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
    preserve_excel_failure,
)
from dart_crawler.excel_model_row_normalization import normalize_model_rows
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_report_arguments import (
    GetReportSectionsArguments,
    ListReportSectionsArguments,
)
from dart_crawler.excel_row_normalization import (
    ExcelSourceValue,
    PendingExcelRow,
    SourcePairs,
)
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result
from dart_crawler.section_models import (
    ReportSectionData,
    ReportSectionList,
    SectionBlock,
    SectionData,
    SectionSummary,
    TableData,
)

_BLOCK_COLUMNS = (
    "rcept_no",
    "attachment_id",
    "section_id",
    "section_title",
    "section_kind",
    "block_index",
    "block_kind",
    "table_row_index",
)
_BLOCK_SOURCE_COLUMNS = ("text", "image_source", "merged_ranges")


def normalize_list_report_sections(
    arguments: ListReportSectionsArguments,
    result: Result[ReportSectionList],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    context = (
        ("rcept_no", arguments.rcept_no),
        ("attachment_id", arguments.attachment_id),
        ("report_title", source.report_title),
        ("source_type", source.source_type),
        ("source_sha256", source.source_sha256),
        ("parser_version", source.parser_version),
        ("coverage_complete", source.coverage_complete),
    )
    return normalize_model_rows(
        domain=ExcelDataDomain.LIST_REPORT_SECTIONS,
        arguments=arguments,
        context_columns=tuple(name for name, _value in context),
        context=context,
        source_model=SectionSummary,
        models=source.sections,
        warnings=result.warnings,
        next_action=result.next_action,
        provenance=NormalizedExcelProvenance(
            domain=ExcelDataDomain.LIST_REPORT_SECTIONS,
            source_rows=len(source.sections),
            normalized_rows=len(source.sections),
            source_sections=len(source.sections),
            reported_rows=source.section_count,
            source_sha256=source.source_sha256,
            parser_version=source.parser_version,
            source_type=source.source_type,
            report_title=source.report_title,
            coverage_complete=source.coverage_complete,
        ),
    )


def normalize_get_report_sections(
    arguments: GetReportSectionsArguments,
    result: Result[ReportSectionData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    rows = tuple(
        row
        for section in source.sections
        for block_index, block in enumerate(section.blocks, start=1)
        for row in _block_rows(
            arguments.rcept_no,
            arguments.attachment_id,
            section,
            block,
            block_index,
        )
    )
    source_blocks = sum(len(section.blocks) for section in source.sections)
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.GET_REPORT_SECTIONS,
            arguments=arguments,
            context_columns=_BLOCK_COLUMNS,
            source_columns=_BLOCK_SOURCE_COLUMNS,
            rows=rows,
            warnings=result.warnings,
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.GET_REPORT_SECTIONS,
                source_rows=len(rows),
                normalized_rows=len(rows),
                source_sections=len(source.sections),
                source_blocks=source_blocks,
                source_sha256=source.source_sha256,
                parser_version=source.parser_version,
            ),
            next_action=result.next_action,
        )
    )


def _block_rows(
    rcept_no: str,
    attachment_id: str,
    section: SectionData,
    block: SectionBlock,
    block_index: int,
) -> tuple[PendingExcelRow, ...]:
    match block.kind:  # noqa: MATCH_OK — BasedPyright enforces exhaustive closed-union coverage
        case BlockKind.TABLE:
            if block.table is None:
                return ()
            return _table_rows(
                rcept_no,
                attachment_id,
                section,
                block.table,
                block_index,
            )
        case BlockKind.HEADING | BlockKind.PARAGRAPH | BlockKind.IMAGE:
            context = _block_context(
                rcept_no,
                attachment_id,
                section,
                block_index,
                block.kind,
                None,
            )
            source: SourcePairs = (
                ("text", block.text),
                ("image_source", block.image_source),
                ("merged_ranges", None),
            )
            return (PendingExcelRow(context, source),)


def _table_rows(
    rcept_no: str,
    attachment_id: str,
    section: SectionData,
    table: TableData,
    block_index: int,
) -> tuple[PendingExcelRow, ...]:
    merged_ranges = _merged_ranges(table)
    rows: list[PendingExcelRow] = []
    for row_index, cells in enumerate(table.rows, start=1):
        context = _block_context(
            rcept_no,
            attachment_id,
            section,
            block_index,
            BlockKind.TABLE,
            row_index,
        )
        source: list[tuple[str, ExcelSourceValue]] = [
            ("text", None),
            ("image_source", None),
            ("merged_ranges", merged_ranges),
        ]
        source.extend(
            (f"column_{index}", cell)
            for index, cell in enumerate(cells, start=1)
        )
        rows.append(PendingExcelRow(context, tuple(source)))
    return tuple(rows)


def _block_context(
    rcept_no: str,
    attachment_id: str,
    section: SectionData,
    block_index: int,
    block_kind: BlockKind,
    table_row_index: int | None,
) -> SourcePairs:
    return (
        ("rcept_no", rcept_no),
        ("attachment_id", attachment_id),
        ("section_id", section.section_id),
        ("section_title", section.title),
        ("section_kind", section.kind.value),
        ("block_index", block_index),
        ("block_kind", block_kind.value),
        ("table_row_index", table_row_index),
    )


def _merged_ranges(table: TableData) -> list[ExcelSourceValue]:
    ranges: list[ExcelSourceValue] = []
    for merged_range in table.merged_ranges:
        coordinates: list[ExcelSourceValue] = list(merged_range)
        ranges.append(coordinates)
    return ranges
