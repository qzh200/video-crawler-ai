from dataclasses import FrozenInstanceError

import pytest

from video_crawler.core.config import Settings
from video_crawler.domain.strategy import CrawlStrategy


def test_video_limit_must_be_within_contract() -> None:
    with pytest.raises(ValueError, match="video_limit"):
        CrawlStrategy(video_limit=501)


def test_zero_root_comment_limit_means_unlimited() -> None:
    strategy = CrawlStrategy(max_root_comments=0)
    assert strategy.max_root_comments == 0


def test_strategy_uses_exact_contract_defaults() -> None:
    assert CrawlStrategy() == CrawlStrategy(
        video_limit=100,
        max_root_comments=1000,
        fetch_all_replies=True,
        fetch_all_danmaku=True,
        fetch_all_subtitles=True,
        timed_text_batch_size=1000,
        max_retries=3,
        video_delay_min_seconds=1.0,
        video_delay_max_seconds=3.0,
        comment_page_delay_min_seconds=0.8,
        comment_page_delay_max_seconds=1.5,
        request_timeout_seconds=30,
        page_timeout_seconds=60,
    )


def test_strategy_from_defaults_reads_settings_values() -> None:
    settings = Settings(
        mysql_password="x",  # noqa: S106 - synthetic test credential
        minio_secret_key="x",  # noqa: S106 - synthetic test credential
        api_key="x",
        default_video_limit=25,
        default_max_retries=2,
    )

    strategy = CrawlStrategy.from_defaults(settings)

    assert strategy.video_limit == 25
    assert strategy.max_retries == 2


def test_strategy_merge_validates_overrides_and_preserves_original() -> None:
    original = CrawlStrategy()

    merged = original.merge({"video_limit": 10, "max_retries": 1})

    assert merged.video_limit == 10
    assert merged.max_retries == 1
    assert original.video_limit == 100


def test_strategy_merge_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown strategy override"):
        CrawlStrategy().merge({"unknown": 1})


def test_strategy_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        CrawlStrategy().__setattr__("video_limit", 10)
