from __future__ import annotations

from collections.abc import AsyncIterator

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili.auth import (
    BilibiliAuthVerification,
    verify_bilibili_auth,
)
from video_crawler.adapters.bilibili.comments import fetch_bilibili_comments
from video_crawler.adapters.bilibili.discovery import discover_popular_targets
from video_crawler.adapters.bilibili.matcher import match_bilibili_url
from video_crawler.adapters.bilibili.metrics import fetch_bilibili_metrics
from video_crawler.adapters.bilibili.resolver import (
    PLATFORM_KEY,
    resolve_bilibili_target,
)
from video_crawler.adapters.bilibili.timed_text import fetch_bilibili_timed_text
from video_crawler.domain.comments import CommentBatch
from video_crawler.domain.metrics import MetricResult
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import DiscoveredTarget, ResolvedTarget, VideoTarget
from video_crawler.domain.timed_text import TimedTextBatch


class BilibiliAdapter:
    platform_key = PLATFORM_KEY

    def match(self, url: str) -> bool:
        return match_bilibili_url(url)

    async def verify_auth(self, context: AdapterContext) -> BilibiliAuthVerification:
        return await verify_bilibili_auth(context)

    async def resolve_target(self, context: AdapterContext, url: str) -> ResolvedTarget:
        return await resolve_bilibili_target(context, url)

    def discover_targets(
        self,
        context: AdapterContext,
        target: ResolvedTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[DiscoveredTarget]:
        return discover_popular_targets(context, target, strategy)

    async def fetch_metrics(
        self,
        context: AdapterContext,
        target: VideoTarget,
    ) -> MetricResult:
        return await fetch_bilibili_metrics(context, target)

    def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]:
        return fetch_bilibili_comments(context, target, strategy)

    def fetch_timed_text(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[TimedTextBatch]:
        return fetch_bilibili_timed_text(context, target, strategy)
