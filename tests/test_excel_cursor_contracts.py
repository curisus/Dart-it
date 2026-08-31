import base64
import hashlib
import hmac
from typing import TypeVar

from pydantic import SecretBytes

from dart_crawler import excel_load_contracts as contracts
from dart_crawler.result import Result

_SECRET_BYTES = b"s" * 32
T = TypeVar("T")


def _signed_token(payload_bytes: bytes) -> str:
    signature = hmac.new(_SECRET_BYTES, payload_bytes, hashlib.sha256).digest()
    payload_part = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    signature_part = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload_part}.{signature_part}"


def _secret() -> contracts.CursorSecret:
    return contracts.CursorSecret(value=SecretBytes(_SECRET_BYTES))


def _signed_cursor_with_offset_digits(digit_count: int) -> str:
    payload = contracts.ExcelCursorPayload(
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        offset=int("7" * digit_count),
        page_index=1,
        page_size=1_000,
    )
    return contracts.encode_excel_cursor(payload, secret=_secret())


def _reason(result: Result[T]) -> str:
    assert result.data is None
    assert result.warnings == ()
    assert result.error is not None
    assert result.error.retryable is False
    assert set(result.error.details) == {"reason"}
    reason = result.error.details["reason"]
    assert isinstance(reason, str)
    return reason


def test_cursor_round_trip_uses_only_the_canonical_signed_payload() -> None:
    # Given: a validated 32-byte secret and the exact seven-field cursor payload.
    secret = _secret()
    payload = contracts.ExcelCursorPayload(
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        offset=125,
        page_index=2,
        page_size=1_000,
    )
    binding = contracts.CursorBinding(
        request_fingerprint="a" * 64,
        page_size=1_000,
    )

    # When: the payload is encoded twice and decoded for the same request.
    token = contracts.encode_excel_cursor(payload, secret=secret)
    decoded = contracts.decode_excel_cursor(
        token,
        secret=secret,
        binding=binding,
    )

    # Then: encoding is deterministic, unpadded, and exposes no obsolete fields.
    assert token == contracts.encode_excel_cursor(payload, secret=secret)
    assert "=" not in token
    assert decoded.ok is True
    assert decoded.data == payload
    assert set(contracts.ExcelCursorPayload.model_fields) == {
        "version",
        "schema_version",
        "request_fingerprint",
        "source_fingerprint",
        "offset",
        "page_index",
        "page_size",
    }


def test_cursor_reports_schema_mismatch_before_other_binding_mismatches() -> None:
    # Given: a validly signed cursor whose schema, request, and page size all differ.
    raw_payload = b"".join(
        [
            b'{"offset":1,"page_index":1,"page_size":1,',
            b'"request_fingerprint":"',
            b"c" * 64,
            b'",',
            b'"schema_version":2,"source_fingerprint":"',
            b"d" * 64,
            b'",',
            b'"version":2}',
        ]
    )
    binding = contracts.CursorBinding(
        request_fingerprint="a" * 64,
        page_size=1_000,
    )

    # When: pre-query cursor validation processes the signed token.
    result = contracts.decode_excel_cursor(
        _signed_token(raw_payload),
        secret=_secret(),
        binding=binding,
    )

    # Then: the dedicated schema reason wins and no warning or data leaks.
    assert _reason(result) == "cursor_schema_mismatch"
    assert result.next_action == "커서 없이 첫 페이지부터 다시 요청하세요."


def test_cursor_rejects_tampering_duplicate_keys_and_oversized_input() -> None:
    # Given: one valid token and independently signed malformed payloads.
    secret = _secret()
    payload = contracts.ExcelCursorPayload(
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        offset=1,
        page_index=1,
        page_size=1_000,
    )
    binding = contracts.CursorBinding(
        request_fingerprint="a" * 64,
        page_size=1_000,
    )
    token = contracts.encode_excel_cursor(payload, secret=secret)
    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
    duplicate = _signed_token(b"".join(
        [
            b'{"offset":1,"page_index":1,"page_size":1000,',
            b'"request_fingerprint":"',
            b"a" * 64,
            b'",',
            b'"schema_version":1,"source_fingerprint":"',
            b"b" * 64,
            b'",',
            b'"version":1,"version":1}',
        ]
    ))
    oversized = _signed_token(b"{" + (b" " * 4_096) + b"}")

    # When: each hostile token is decoded before any upstream query.
    results = tuple(
        contracts.decode_excel_cursor(candidate, secret=secret, binding=binding)
        for candidate in (tampered, duplicate, oversized)
    )

    # Then: every failure is the same redacted pre-query contract error.
    assert tuple(_reason(result) for result in results) == (
        "invalid_cursor",
        "invalid_cursor",
        "invalid_cursor",
    )
    assert all(result.next_action == "커서 없이 첫 페이지부터 다시 요청하세요." for result in results)


def test_cursor_accepts_exactly_4096_utf8_transport_bytes() -> None:
    # Given: a normally signed cursor whose transport representation is exactly 4096 bytes.
    token = _signed_cursor_with_offset_digits(2_788)
    binding = contracts.CursorBinding(
        request_fingerprint="a" * 64,
        page_size=1_000,
    )

    # When: the exact boundary cursor is decoded.
    result = contracts.decode_excel_cursor(token, secret=_secret(), binding=binding)

    # Then: the otherwise valid cursor is accepted at the inclusive boundary.
    assert len(token.encode("utf-8")) == 4_096
    assert result.ok is True


def test_cursor_rejects_4097_byte_transport_string() -> None:
    # Given: a cursor transport string one byte beyond the configured boundary.
    token = "a" * 4_097
    binding = contracts.CursorBinding(
        request_fingerprint="a" * 64,
        page_size=1_000,
    )

    # When: the oversized transport string is decoded.
    result = contracts.decode_excel_cursor(token, secret=_secret(), binding=binding)

    # Then: it is rejected as an invalid cursor.
    assert len(token.encode("utf-8")) == 4_097
    assert _reason(result) == "invalid_cursor"


def test_cursor_rejects_normally_signed_transport_string_over_4096_bytes() -> None:
    # Given: a normally signed cursor whose encoded transport string is 4098 bytes.
    token = _signed_cursor_with_offset_digits(2_789)
    binding = contracts.CursorBinding(
        request_fingerprint="a" * 64,
        page_size=1_000,
    )

    # When: the signed oversized cursor is decoded.
    result = contracts.decode_excel_cursor(token, secret=_secret(), binding=binding)

    # Then: transport size rejects it before payload processing.
    assert len(token.encode("utf-8")) == 4_098
    assert _reason(result) == "invalid_cursor"


def test_cursor_binding_reports_request_before_page_size_mismatch() -> None:
    # Given: a valid cursor and bindings that disagree with its request and page size.
    secret = _secret()
    payload = contracts.ExcelCursorPayload(
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        offset=1,
        page_index=1,
        page_size=1_000,
    )
    token = contracts.encode_excel_cursor(payload, secret=secret)

    # When: both mismatches and then only the page-size mismatch are validated.
    both = contracts.decode_excel_cursor(
        token,
        secret=secret,
        binding=contracts.CursorBinding(
            request_fingerprint="c" * 64,
            page_size=1,
        ),
    )
    page_only = contracts.decode_excel_cursor(
        token,
        secret=secret,
        binding=contracts.CursorBinding(
            request_fingerprint="a" * 64,
            page_size=1,
        ),
    )

    # Then: request mismatch wins, and page mismatch remains independently typed.
    assert _reason(both) == "cursor_request_mismatch"
    assert _reason(page_only) == "cursor_page_size_mismatch"


def test_cursor_secret_uses_utf8_byte_length_without_exposing_secret() -> None:
    # Given: secrets immediately below and above the 32-byte UTF-8 boundary.
    short_secret = "x" * 31
    multibyte_secret = "가" * 11

    # When: boundary validation creates request-scoped secret values.
    rejected = contracts.cursor_secret_from_text(short_secret)
    accepted = contracts.cursor_secret_from_text(multibyte_secret)

    # Then: byte length controls acceptance and errors contain no secret material.
    assert _reason(rejected) == "invalid_request"
    assert accepted.ok is True
    assert accepted.data is not None
    assert accepted.data.value.get_secret_value() == multibyte_secret.encode("utf-8")
    assert short_secret not in repr(rejected)


def test_source_change_precedes_position_validation_after_one_query() -> None:
    # Given: a continuation cursor whose source and terminal position are stale.
    payload = contracts.ExcelCursorPayload(
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        offset=2,
        page_index=1,
        page_size=1_000,
    )
    upstream_calls = 0

    # When: a single query returns the current source state before post-query checks.
    def query_once() -> contracts.CursorDatasetState:
        nonlocal upstream_calls
        upstream_calls += 1
        return contracts.CursorDatasetState(
            source_fingerprint="c" * 64,
            total_row_count=2,
        )

    result = contracts.validate_cursor_after_query(payload, query_once())

    # Then: source change wins over invalid position after exactly one query.
    assert upstream_calls == 1
    assert _reason(result) == "source_changed"


def test_cursor_position_is_validated_against_matching_source() -> None:
    # Given: a continuation cursor positioned at the end of an unchanged source.
    payload = contracts.ExcelCursorPayload(
        request_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        offset=2,
        page_index=1,
        page_size=1_000,
    )
    state = contracts.CursorDatasetState(
        source_fingerprint="b" * 64,
        total_row_count=2,
    )

    # When: post-query cursor position validation runs.
    result = contracts.validate_cursor_after_query(payload, state)

    # Then: the dedicated position failure carries the restart action.
    assert _reason(result) == "cursor_position_invalid"
    assert result.next_action == "커서 없이 첫 페이지부터 다시 요청하세요."
