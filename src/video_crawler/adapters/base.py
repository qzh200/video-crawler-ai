from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from video_crawler.application.gateways import (
    AuthProfileContext,
    BoundLogger,
    BrowserGateway,
    CancellationToken,
    HttpGateway,
    NetworkCaptureGateway,
    RateLimiter,
    RawArtifactGateway,
)
from video_crawler.domain.comments import CommentBatch
from video_crawler.domain.metrics import MetricResult
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import DiscoveredTarget, ResolvedTarget, VideoTarget
from video_crawler.domain.timed_text import TimedTextBatch


class AuthVerificationResult(Protocol):
    @property
    def is_valid(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...

    @property
    def extra(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AdapterContext:
    browser: BrowserGateway
    http: HttpGateway
    network_capture: NetworkCaptureGateway
    raw_artifacts: RawArtifactGateway
    rate_limiter: RateLimiter
    cancellation: CancellationToken
    logger: BoundLogger
    auth_profile: AuthProfileContext


class VideoSiteAdapter(Protocol):
    platform_key: str

    def match(self, url: str) -> bool: ...

    async def verify_auth(self, context: AdapterContext) -> AuthVerificationResult: ...

    async def resolve_target(self, context: AdapterContext, url: str) -> ResolvedTarget: ...

    def discover_targets(
        self,
        context: AdapterContext,
        target: ResolvedTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[DiscoveredTarget]: ...

    async def fetch_metrics(
        self,
        context: AdapterContext,
        target: VideoTarget,
    ) -> MetricResult: ...

    def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]: ...

    def fetch_timed_text(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[TimedTextBatch]: ...
