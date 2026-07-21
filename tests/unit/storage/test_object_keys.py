from datetime import UTC, datetime
from uuid import UUID

import pytest

from video_crawler.infrastructure.storage.minio import build_object_key


def test_object_key_is_deterministic_and_contains_required_segments() -> None:
    captured_at = datetime(2026, 7, 21, 12, 30, tzinfo=UTC)
    run_id = UUID("01900000-0000-7000-8000-000000000002")

    key = build_object_key(
        "bilibili",
        captured_at,
        "video-001",
        run_id,
        "metrics.json",
    )

    assert key == (
        "bilibili/2026/07/21/video-001/01900000-0000-7000-8000-000000000002/metrics.json"
    )
    assert "?" not in key
    assert "token" not in key


@pytest.mark.parametrize(
    "unsafe",
    ["../secret", "video/child", "value?token=secret", "value#fragment", ""],
)
def test_object_key_rejects_unsafe_segments(unsafe: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        build_object_key("bilibili", datetime.now(UTC), unsafe, "run", "artifact.json")
