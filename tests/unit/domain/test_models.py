from datetime import UTC, datetime

import pytest

from video_crawler.domain.comments import NormalizedComment
from video_crawler.domain.metrics import MetricStatus, MetricValue
from video_crawler.domain.targets import DiscoveredTarget


def test_metric_value_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="value"):
        MetricValue(value=-1, status=MetricStatus.AVAILABLE)


def test_metric_value_enforces_status_value_consistency() -> None:
    with pytest.raises(ValueError, match="available"):
        MetricValue(value=None, status=MetricStatus.AVAILABLE)
    with pytest.raises(ValueError, match="must be None"):
        MetricValue(value=0, status=MetricStatus.NOT_PUBLIC)


def test_comment_rejects_negative_counts_and_naive_time() -> None:
    values = {
        "platform_comment_id": "comment-1",
        "root_platform_comment_id": None,
        "parent_platform_comment_id": None,
        "author_platform_id": None,
        "author_name": None,
        "content": "hello",
        "like_count": 0,
        "reply_count": 0,
        "published_at": datetime(2026, 7, 19, tzinfo=UTC),
        "status": "visible",
    }

    with pytest.raises(ValueError, match="like_count"):
        NormalizedComment(**(values | {"like_count": -1}))
    with pytest.raises(ValueError, match="reply_count"):
        NormalizedComment(**(values | {"reply_count": -1}))
    with pytest.raises(ValueError, match="published_at"):
        NormalizedComment(**(values | {"published_at": datetime(2026, 7, 19)}))


def test_discovered_target_rejects_negative_position() -> None:
    with pytest.raises(ValueError, match="position"):
        DiscoveredTarget("example", "video-1", "https://example.test/v/1", -1)
