from datetime import UTC, datetime

import pytest

from video_crawler.application.cursors import (
    CommentCursor,
    CursorCodec,
    InvalidCursorError,
    TimedTextCursor,
)


def test_comment_cursor_round_trip() -> None:
    codec = CursorCodec(b"test-cursor-secret")
    cursor = CommentCursor(
        published_at=datetime(2026, 7, 22, 10, 30, 45, 123000, tzinfo=UTC),
        id=42,
    )

    encoded = codec.encode_comment(cursor)

    assert encoded != ""
    assert codec.decode_comment(encoded) == cursor


def test_timed_text_cursor_round_trip() -> None:
    codec = CursorCodec(b"test-cursor-secret")
    cursor = TimedTextCursor(start_ms=12_345, id=84)

    assert codec.decode_timed_text(codec.encode_timed_text(cursor)) == cursor


def test_tampered_cursor_is_rejected() -> None:
    codec = CursorCodec(b"test-cursor-secret")
    encoded = codec.encode_timed_text(TimedTextCursor(start_ms=1000, id=1))
    replacement = "A" if encoded[-1] != "A" else "B"

    with pytest.raises(InvalidCursorError, match="invalid cursor"):
        codec.decode_timed_text(encoded[:-1] + replacement)


def test_cursor_kind_cannot_be_reused() -> None:
    codec = CursorCodec(b"test-cursor-secret")
    encoded = codec.encode_comment(
        CommentCursor(published_at=datetime(2026, 7, 22, tzinfo=UTC), id=1)
    )

    with pytest.raises(InvalidCursorError, match="cursor kind"):
        codec.decode_timed_text(encoded)
