import dataclasses

import pytest

from dart_crawler.document_model import (
    BlockKind,
    DocumentBlock,
    DocumentSection,
    ParsedDocument,
    SectionKind,
    SourceCoverage,
)
from dart_crawler.document_validation import validate_document
from dart_crawler.result import ErrorCode


def _complete_coverage() -> SourceCoverage:
    return SourceCoverage(
        source_text_token_count=0,
        captured_text_token_count=0,
        source_text_sha256="a" * 64,
        captured_text_sha256="a" * 64,
        source_table_count=1,
        captured_table_count=1,
        source_cell_count=3,
        captured_cell_count=3,
        source_image_count=0,
        captured_image_count=0,
    )


@pytest.mark.parametrize(
    "coverage",
    [
        dataclasses.replace(_complete_coverage(), source_text_token_count=1),
        dataclasses.replace(_complete_coverage(), captured_text_sha256="b" * 64),
        dataclasses.replace(_complete_coverage(), captured_table_count=0),
        dataclasses.replace(_complete_coverage(), captured_cell_count=2),
        dataclasses.replace(_complete_coverage(), source_image_count=1),
    ],
    ids=[
        "token_count",
        "token_order_sha256",
        "table_count",
        "cell_count",
        "image_count",
    ],
)
def test_validate_document_rejects_each_isolated_coverage_mismatch(
    coverage: SourceCoverage,
) -> None:
    document = ParsedDocument(
        sections=(
            DocumentSection(
                title="본문",
                kind=SectionKind.OTHER,
                blocks=(DocumentBlock(BlockKind.PARAGRAPH, text="captured"),),
            ),
        ),
        source_sha256="a" * 64,
        source_type="xml",
        source_coverage=coverage,
    )

    result = validate_document(document)

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ErrorCode.VALIDATION_FAILED
    assert result.error.details["issue"] == "incomplete_source_coverage"

