from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any, Protocol, Self

from video_crawler.domain.errors import DomainValidationError


class StrategyDefaults(Protocol):
    default_video_limit: int
    default_max_root_comments: int
    default_fetch_all_replies: bool
    default_fetch_all_danmaku: bool
    default_fetch_all_subtitles: bool
    default_timed_text_batch_size: int
    default_max_retries: int
    default_video_delay_min_seconds: float
    default_video_delay_max_seconds: float
    default_comment_page_delay_min_seconds: float
    default_comment_page_delay_max_seconds: float
    default_request_timeout_seconds: int
    default_page_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class CrawlStrategy:
    video_limit: int = 100
    max_root_comments: int = 1000
    fetch_all_replies: bool = True
    fetch_all_danmaku: bool = True
    fetch_all_subtitles: bool = True
    timed_text_batch_size: int = 1000
    max_retries: int = 3
    video_delay_min_seconds: float = 1.0
    video_delay_max_seconds: float = 3.0
    comment_page_delay_min_seconds: float = 0.8
    comment_page_delay_max_seconds: float = 1.5
    request_timeout_seconds: int = 30
    page_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        _validate_int_range("video_limit", self.video_limit, 1, 500)
        _validate_int_range("max_root_comments", self.max_root_comments, 0, 100_000)
        _validate_int_range("timed_text_batch_size", self.timed_text_batch_size, 100, 5000)
        _validate_int_range("max_retries", self.max_retries, 0, 5)
        _validate_float_min("video_delay_min_seconds", self.video_delay_min_seconds, 0.5)
        _validate_float_min("video_delay_max_seconds", self.video_delay_max_seconds, 0.5)
        _validate_float_min(
            "comment_page_delay_min_seconds",
            self.comment_page_delay_min_seconds,
            0.5,
        )
        _validate_float_min(
            "comment_page_delay_max_seconds",
            self.comment_page_delay_max_seconds,
            0.5,
        )
        _validate_int_range("request_timeout_seconds", self.request_timeout_seconds, 5, 120)
        _validate_int_range("page_timeout_seconds", self.page_timeout_seconds, 10, 300)
        for name in (
            "fetch_all_replies",
            "fetch_all_danmaku",
            "fetch_all_subtitles",
        ):
            if not isinstance(getattr(self, name), bool):
                raise DomainValidationError(f"{name} must be a boolean")
        if self.video_delay_min_seconds > self.video_delay_max_seconds:
            raise DomainValidationError("video delay min must not exceed video delay max")
        if self.comment_page_delay_min_seconds > self.comment_page_delay_max_seconds:
            raise DomainValidationError(
                "comment page delay min must not exceed comment page delay max"
            )

    @classmethod
    def from_defaults(cls, settings: StrategyDefaults) -> Self:
        return cls(
            video_limit=settings.default_video_limit,
            max_root_comments=settings.default_max_root_comments,
            fetch_all_replies=settings.default_fetch_all_replies,
            fetch_all_danmaku=settings.default_fetch_all_danmaku,
            fetch_all_subtitles=settings.default_fetch_all_subtitles,
            timed_text_batch_size=settings.default_timed_text_batch_size,
            max_retries=settings.default_max_retries,
            video_delay_min_seconds=settings.default_video_delay_min_seconds,
            video_delay_max_seconds=settings.default_video_delay_max_seconds,
            comment_page_delay_min_seconds=settings.default_comment_page_delay_min_seconds,
            comment_page_delay_max_seconds=settings.default_comment_page_delay_max_seconds,
            request_timeout_seconds=settings.default_request_timeout_seconds,
            page_timeout_seconds=settings.default_page_timeout_seconds,
        )

    def merge(self, overrides: Mapping[str, object]) -> Self:
        valid_names = {field.name for field in fields(self)}
        unknown_names = sorted(set(overrides) - valid_names)
        if unknown_names:
            names = ", ".join(unknown_names)
            raise DomainValidationError(f"unknown strategy override: {names}")
        validated_at_construction: dict[str, Any] = dict(overrides)
        return replace(self, **validated_at_construction)


def _validate_int_range(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainValidationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise DomainValidationError(f"{name} must be between {minimum} and {maximum}")


def _validate_float_min(name: str, value: float, minimum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DomainValidationError(f"{name} must be a number")
    if value < minimum:
        raise DomainValidationError(f"{name} must be at least {minimum}")
