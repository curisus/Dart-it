from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

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
