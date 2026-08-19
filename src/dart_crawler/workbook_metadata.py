"""Shared workbook metadata expectations used for writing and validation."""

from typing import Final, Protocol

from dart_crawler.document_model import ParsedDocument
from dart_crawler.document_validation import ValidationSummary

RCEPT_NO_KEY: Final = "rcept_no"
SOURCE_RCEPT_NO_KEY: Final = "source_rcept_no"
ATTACHMENT_ID_KEY: Final = "attachment_id"
SOURCE_SHA256_KEY: Final = "source_sha256"
COLLECTION_STATUS_KEY: Final = "collection_status"
VALIDATION_STATUS_KEY: Final = "validation_status"
VALIDATED_CELL_COUNT_KEY: Final = "validated_cell_count"
VALIDATED_MERGE_COUNT_KEY: Final = "validated_merge_count"


class ValidationContext(Protocol):
    """Export identity fields required by workbook metadata validation."""

    @property
    def rcept_no(self) -> str: ...

    @property
    def source_rcept_no(self) -> str: ...

    @property
    def attachment_id(self) -> str: ...

    @property
    def document(self) -> ParsedDocument: ...


def shared_metadata_expectations(
    context: ValidationContext,
    *,
    collection_status: str,
    summary: ValidationSummary,
) -> dict[str, str]:
    """Return metadata values that writing and validation must share."""
    return {
        RCEPT_NO_KEY: context.rcept_no,
        SOURCE_RCEPT_NO_KEY: context.source_rcept_no,
        ATTACHMENT_ID_KEY: context.attachment_id,
        SOURCE_SHA256_KEY: context.document.source_sha256,
        COLLECTION_STATUS_KEY: collection_status,
        VALIDATION_STATUS_KEY: "passed",
        VALIDATED_CELL_COUNT_KEY: str(summary.checked_cell_count),
        VALIDATED_MERGE_COUNT_KEY: str(summary.checked_merge_count),
    }
