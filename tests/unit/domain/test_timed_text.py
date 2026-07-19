from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from video_crawler.domain.timed_text import (
    NormalizedTimedText,
    TimedTextType,
    build_timed_text_dedup_key,
)


def test_platform_item_id_has_priority_for_dedup() -> None:
    item = NormalizedTimedText(
        platform_item_id="42",
        start_ms=1000,
        end_ms=None,
        text="hello",
        published_at=None,
        sender_ref=None,
        attributes={},
    )
    first = build_timed_text_dedup_key(item, TimedTextType.DANMAKU)
    changed = replace(item, text="changed")
    assert first == build_timed_text_dedup_key(changed, TimedTextType.DANMAKU)
    assert first == sha256(b"42").hexdigest()


def test_subtitle_without_platform_id_uses_timing_and_text() -> None:
    item = NormalizedTimedText(
        platform_item_id=None,
        start_ms=1000,
        end_ms=2000,
        text="hello",
        published_at=None,
        sender_ref=None,
    )

    assert (
        build_timed_text_dedup_key(item, TimedTextType.SUBTITLE)
        == sha256(b"1000|2000|hello").hexdigest()
    )


def test_danmaku_without_platform_id_uses_publication_sender_and_text() -> None:
    published_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    item = NormalizedTimedText(
        platform_item_id=None,
        start_ms=1000,
        end_ms=None,
        text="hello",
        published_at=published_at,
        sender_ref="sender",
    )

    expected = sha256(b"1000|2026-07-19T12:00:00+00:00|sender|hello").hexdigest()
    assert build_timed_text_dedup_key(item, TimedTextType.DANMAKU) == expected


def test_timed_text_rejects_negative_or_reversed_times() -> None:
    with pytest.raises(ValueError, match="start_ms"):
        NormalizedTimedText(None, -1, None, "hello", None, None)
    with pytest.raises(ValueError, match="end_ms"):
        NormalizedTimedText(None, 1000, 999, "hello", None, None)


def test_timed_text_rejects_naive_publication_time() -> None:
    with pytest.raises(ValueError, match="published_at"):
        NormalizedTimedText(None, 0, None, "hello", datetime(2026, 7, 19), None)
