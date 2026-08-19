from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from dart_crawler.attachments import _EXTENDED_NAME_MARKER
from dart_crawler.zip_safety import ArchiveLimits, inspect_archive, read_member


def _zip_file(name: str, content: bytes) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def test_archive_member_is_read_when_within_limits() -> None:
    archive = _zip_file("CORPCODE.xml", b"<result />")

    result = read_member(archive, "CORPCODE.xml", limits=ArchiveLimits())

    assert result.ok is True
    assert result.data == b"<result />"


def test_archive_path_traversal_is_rejected() -> None:
    archive = _zip_file("../outside.xml", b"unsafe")

    result = inspect_archive(archive, limits=ArchiveLimits())

    assert result.ok is False
    assert result.error is not None
    assert result.error.code.value == "PARSE_FAILED"


def test_archive_member_beginning_with_extended_name_marker_is_rejected() -> None:
    # Given
    member_name = f"{_EXTENDED_NAME_MARKER}legacy.xml"
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(ZipInfo(member_name), b"unsafe")
    archive_bytes = buffer.getvalue()
    with ZipFile(BytesIO(archive_bytes)) as archive:
        stored_name = archive.infolist()[0].filename
    if stored_name != member_name:
        pytest.skip("zipfile did not preserve the leading extended-name marker")

    # When
    result = inspect_archive(archive_bytes, limits=ArchiveLimits())

    # Then
    # If this stops holding, a legacy identifier could begin with the marker and
    # be read as an extended one, resolving to bytes from a different filing.
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code.value == "PARSE_FAILED"
