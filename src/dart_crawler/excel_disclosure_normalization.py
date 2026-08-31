from dart_crawler.domains.material_events import MaterialEventData, MaterialEventRows
from dart_crawler.domains.ownership import OwnershipReportData
from dart_crawler.domains.registration_statements import RegistrationStatementData
from dart_crawler.domains.report_topics import ReportTopicData, ReportTopicRows
from dart_crawler.excel_dataset_builder import (
    ExcelSourceDataset,
    normalize_excel_source,
    preserve_excel_failure,
)
from dart_crawler.excel_disclosure_arguments import (
    GetMaterialEventsArguments,
    GetOwnershipReportsArguments,
    GetRegistrationStatementsArguments,
    GetReportTopicsArguments,
)
from dart_crawler.excel_page_models import ExcelDataDomain
from dart_crawler.excel_row_normalization import PendingExcelRow, SourcePairs
from dart_crawler.excel_source_values import json_object_pairs
from dart_crawler.normalized_excel_models import (
    NormalizedExcelDataset,
    NormalizedExcelProvenance,
)
from dart_crawler.result import Result


def normalize_report_topics(
    arguments: GetReportTopicsArguments,
    result: Result[ReportTopicData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    rows: list[PendingExcelRow] = []
    for topic in arguments.topics:
        group = _topic_group(topic, source.topics)
        if group is None:
            continue
        context: SourcePairs = (
            ("corp_code", arguments.corp_code),
            ("bsns_year", arguments.bsns_year),
            ("reprt_code", arguments.reprt_code),
            ("topic", topic),
            ("label", group.label),
        )
        rows.extend(
            PendingExcelRow(context, json_object_pairs(row))
            for row in group.rows
        )
    normalized_rows = tuple(rows)
    source_row_count = sum(len(group.rows) for group in source.topics)
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.GET_REPORT_TOPICS,
            arguments=arguments,
            context_columns=(
                "corp_code",
                "bsns_year",
                "reprt_code",
                "topic",
                "label",
            ),
            source_columns=(),
            rows=normalized_rows,
            warnings=result.warnings,
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.GET_REPORT_TOPICS,
                source_rows=source_row_count,
                normalized_rows=len(normalized_rows),
                source_groups=len(source.topics),
                reported_rows=source.returned_row_count,
            ),
            next_action=result.next_action,
        )
    )


def normalize_ownership_reports(
    arguments: GetOwnershipReportsArguments,
    result: Result[OwnershipReportData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    context: SourcePairs = (
        ("corp_code", arguments.corp_code),
        ("report_type", arguments.report_type),
        ("label", source.label),
        ("bgn_de", arguments.bgn_de),
        ("end_de", arguments.end_de),
    )
    rows = tuple(
        PendingExcelRow(context, json_object_pairs(row)) for row in source.rows
    )
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.GET_OWNERSHIP_REPORTS,
            arguments=arguments,
            context_columns=tuple(name for name, _value in context),
            source_columns=(),
            rows=rows,
            warnings=result.warnings,
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.GET_OWNERSHIP_REPORTS,
                source_rows=len(source.rows),
                normalized_rows=len(rows),
                reported_rows=source.returned_row_count,
                reported_total_rows=source.total_row_count,
            ),
            next_action=result.next_action,
        )
    )


def normalize_material_events(
    arguments: GetMaterialEventsArguments,
    result: Result[MaterialEventData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    rows: list[PendingExcelRow] = []
    for event_type in arguments.event_types:
        group = _event_group(event_type, source.events)
        if group is None:
            continue
        context: SourcePairs = (
            ("corp_code", arguments.corp_code),
            ("event_type", event_type),
            ("label", group.label),
            ("bgn_de", arguments.bgn_de),
            ("end_de", arguments.end_de),
        )
        rows.extend(
            PendingExcelRow(context, json_object_pairs(row))
            for row in group.rows
        )
    normalized_rows = tuple(rows)
    source_row_count = sum(len(group.rows) for group in source.events)
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.GET_MATERIAL_EVENTS,
            arguments=arguments,
            context_columns=(
                "corp_code",
                "event_type",
                "label",
                "bgn_de",
                "end_de",
            ),
            source_columns=(),
            rows=normalized_rows,
            warnings=result.warnings,
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.GET_MATERIAL_EVENTS,
                source_rows=source_row_count,
                normalized_rows=len(normalized_rows),
                source_groups=len(source.events),
                reported_rows=source.returned_row_count,
            ),
            next_action=result.next_action,
        )
    )


def normalize_registration_statements(
    arguments: GetRegistrationStatementsArguments,
    result: Result[RegistrationStatementData],
) -> Result[NormalizedExcelDataset]:
    if not result.ok or result.data is None:
        return preserve_excel_failure(result)
    source = result.data
    rows: list[PendingExcelRow] = []
    for group_index, group in enumerate(source.groups, start=1):
        context: SourcePairs = (
            ("corp_code", arguments.corp_code),
            ("stmt_type", arguments.stmt_type),
            ("label", source.label),
            ("bgn_de", arguments.bgn_de),
            ("end_de", arguments.end_de),
            ("group_index", group_index),
            ("group_title", group.title),
        )
        rows.extend(
            PendingExcelRow(context, json_object_pairs(row))
            for row in group.rows
        )
    normalized_rows = tuple(rows)
    source_row_count = sum(len(group.rows) for group in source.groups)
    return normalize_excel_source(
        ExcelSourceDataset(
            domain=ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
            arguments=arguments,
            context_columns=(
                "corp_code",
                "stmt_type",
                "label",
                "bgn_de",
                "end_de",
                "group_index",
                "group_title",
            ),
            source_columns=(),
            rows=normalized_rows,
            warnings=result.warnings,
            provenance=NormalizedExcelProvenance(
                domain=ExcelDataDomain.GET_REGISTRATION_STATEMENTS,
                source_rows=source_row_count,
                normalized_rows=len(normalized_rows),
                source_groups=len(source.groups),
                reported_rows=source.returned_row_count,
                reported_groups=source.returned_group_count,
            ),
            next_action=result.next_action,
        )
    )


def _topic_group(
    topic: str,
    groups: tuple[ReportTopicRows, ...],
) -> ReportTopicRows | None:
    return next((group for group in groups if group.topic == topic), None)


def _event_group(
    event_type: str,
    groups: tuple[MaterialEventRows, ...],
) -> MaterialEventRows | None:
    return next(
        (group for group in groups if group.event_type == event_type),
        None,
    )
