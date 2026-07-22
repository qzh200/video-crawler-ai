from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from video_crawler.adapters.base import AdapterContext
from video_crawler.application.pipeline import CrawlJobContext, CrawlPipeline, PipelineStatus
from video_crawler.domain.comments import CommentBatch
from video_crawler.domain.errors import CancellationRequestedError, UpstreamError
from video_crawler.domain.metrics import MetricResult, MetricStatus, MetricValue
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import (
    DiscoveredTarget,
    ResolvedTarget,
    TargetKind,
    VideoTarget,
)
from video_crawler.domain.timed_text import (
    NormalizedTimedText,
    TimedTextBatch,
    TimedTextStreamDescriptor,
    TimedTextType,
)

RUN_ID = UUID("01900000-0000-7000-8000-000000000001")


class FakeAdapter:
    platform_key = "example"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_metrics(
        self,
        context: AdapterContext,
        target: VideoTarget,
    ) -> MetricResult:
        del context, target
        self.calls.append("metrics")
        return MetricResult(values={"standard.views": MetricValue(7, MetricStatus.AVAILABLE)})

    def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]:
        del context, target, strategy
        self.calls.append("comments")
        raise UpstreamError("comments unavailable")

    async def fetch_timed_text(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[TimedTextBatch]:
        del context, target, strategy
        self.calls.append("timed_text")
        yield TimedTextBatch(
            stream=TimedTextStreamDescriptor(
                platform_unit_id="unit-1",
                content_type=TimedTextType.SUBTITLE,
                stream_key="primary",
                language_code="en",
                source_type="fixture",
            ),
            items=(
                NormalizedTimedText(
                    platform_item_id="line-1",
                    start_ms=0,
                    end_ms=1000,
                    text="hello",
                    published_at=None,
                    sender_ref=None,
                ),
            ),
        )


class RecordingResults:
    def __init__(self) -> None:
        self.metrics: list[MetricResult] = []
        self.comments: list[CommentBatch] = []
        self.timed_text: list[TimedTextBatch] = []

    async def create_metric_snapshot(
        self,
        video_id: int,
        crawl_run_id: UUID,
        result: MetricResult,
    ) -> int:
        assert video_id == 11
        assert crawl_run_id == RUN_ID
        self.metrics.append(result)
        return 1

    async def upsert_comments(self, video_id: int, batch: CommentBatch) -> int:
        assert video_id == 11
        self.comments.append(batch)
        return len(batch.items)

    async def upsert_timed_text_batch(self, video_id: int, batch: TimedTextBatch) -> int:
        assert video_id == 11
        self.timed_text.append(batch)
        return len(batch.items)


class RecordingModuleStates:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def mark_running(self, module_key: str) -> None:
        self.events.append((module_key, "running"))

    async def mark_success(self, module_key: str) -> None:
        self.events.append((module_key, "success"))

    async def mark_failed(self, module_key: str, error: Exception) -> None:
        del error
        self.events.append((module_key, "failed"))

    async def mark_skipped(self, module_key: str) -> None:
        self.events.append((module_key, "skipped"))

    async def mark_cancelled(self, module_key: str, error: BaseException) -> None:
        del error
        self.events.append((module_key, "cancelled"))


class NoopCancellation:
    def raise_if_cancelled(self) -> None:
        pass


class ControlledCancellation:
    def __init__(self) -> None:
        self.cancelled = False

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancellationRequestedError("crawl cancellation requested")


class RecoveringAdapter(FakeAdapter):
    async def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]:
        del context, target, strategy
        self.calls.append("comments")
        yield CommentBatch(items=(), cursor=None, has_more=False)


class ListingAdapter(FakeAdapter):
    async def discover_targets(
        self,
        context: AdapterContext,
        target: ResolvedTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[DiscoveredTarget]:
        del context, target, strategy
        self.calls.append("discovery")
        for position in range(2):
            yield DiscoveredTarget(
                platform="example",
                platform_video_id=f"video-{position}",
                canonical_url=f"https://example.test/video/{position}",
                position=position,
            )


class MultiBatchAdapter(RecoveringAdapter):
    async def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]:
        del context, target, strategy
        self.calls.append("comments")
        yield CommentBatch(items=(), cursor="page-1", has_more=True)
        yield CommentBatch(items=(), cursor=None, has_more=False)


class RecordingDiscoveries:
    def __init__(self) -> None:
        self.targets: list[DiscoveredTarget] = []

    async def record_discovered_target(
        self,
        crawl_run_id: UUID,
        target: DiscoveredTarget,
    ) -> None:
        assert crawl_run_id == RUN_ID
        self.targets.append(target)


class CancellingResults(RecordingResults):
    def __init__(self, cancellation: ControlledCancellation) -> None:
        super().__init__()
        self._cancellation = cancellation

    async def upsert_comments(self, video_id: int, batch: CommentBatch) -> int:
        count = await super().upsert_comments(video_id, batch)
        self._cancellation.cancelled = True
        return count


class CancellingModuleStates(RecordingModuleStates):
    def __init__(self, cancellation: ControlledCancellation) -> None:
        super().__init__()
        self._cancellation = cancellation

    async def mark_success(self, module_key: str) -> None:
        await super().mark_success(module_key)
        self._cancellation.cancelled = True


@pytest.mark.asyncio
async def test_pipeline_preserves_successful_modules_when_comments_fail() -> None:
    results = RecordingResults()
    states = RecordingModuleStates()
    pipeline = CrawlPipeline(result_repository=results, module_states=states)
    context = CrawlJobContext(
        adapter=cast("object", FakeAdapter()),
        adapter_context=cast(
            AdapterContext,
            SimpleNamespace(cancellation=NoopCancellation()),
        ),
        target=ResolvedTarget(
            platform="example",
            kind=TargetKind.SINGLE_VIDEO,
            canonical_url="https://example.test/video/1",
            platform_video_id="video-1",
        ),
        strategy=CrawlStrategy(),
        crawl_run_id=RUN_ID,
        video_id=11,
    )

    result = await pipeline.execute(context)

    assert result.status is PipelineStatus.PARTIAL
    assert result.module_states == {
        "metrics": "success",
        "comments": "failed",
        "timed_text": "success",
    }
    assert len(results.metrics) == 1
    assert results.comments == []
    assert len(results.timed_text) == 1
    assert states.events == [
        ("metrics", "running"),
        ("metrics", "success"),
        ("comments", "running"),
        ("comments", "failed"),
        ("timed_text", "running"),
        ("timed_text", "success"),
    ]


@pytest.mark.asyncio
async def test_resume_skips_modules_that_already_succeeded() -> None:
    adapter = RecoveringAdapter()
    results = RecordingResults()
    states = RecordingModuleStates()
    pipeline = CrawlPipeline(result_repository=results, module_states=states)
    context = CrawlJobContext(
        adapter=cast("object", adapter),
        adapter_context=cast(
            AdapterContext,
            SimpleNamespace(cancellation=NoopCancellation()),
        ),
        target=ResolvedTarget(
            platform="example",
            kind=TargetKind.SINGLE_VIDEO,
            canonical_url="https://example.test/video/1",
            platform_video_id="video-1",
        ),
        strategy=CrawlStrategy(),
        crawl_run_id=RUN_ID,
        video_id=11,
        prior_module_states={"metrics": "success", "timed_text": "success"},
    )

    result = await pipeline.execute(context)

    assert adapter.calls == ["comments"]
    assert result.status is PipelineStatus.SUCCESS
    assert result.module_states == {
        "metrics": "skipped",
        "comments": "success",
        "timed_text": "skipped",
    }
    assert states.events == [
        ("metrics", "skipped"),
        ("comments", "running"),
        ("comments", "success"),
        ("timed_text", "skipped"),
    ]


@pytest.mark.asyncio
async def test_list_target_runs_discovery_only() -> None:
    adapter = ListingAdapter()
    discoveries = RecordingDiscoveries()
    states = RecordingModuleStates()
    pipeline = CrawlPipeline(
        result_repository=RecordingResults(),
        module_states=states,
        discovery_repository=discoveries,
    )
    context = CrawlJobContext(
        adapter=cast("object", adapter),
        adapter_context=cast(
            AdapterContext,
            SimpleNamespace(cancellation=NoopCancellation()),
        ),
        target=ResolvedTarget(
            platform="example",
            kind=TargetKind.VIDEO_LIST,
            canonical_url="https://example.test/popular",
        ),
        strategy=CrawlStrategy(),
        crawl_run_id=RUN_ID,
    )

    result = await pipeline.execute(context)

    assert adapter.calls == ["discovery"]
    assert [target.position for target in discoveries.targets] == [0, 1]
    assert result.status is PipelineStatus.SUCCESS
    assert result.module_states == {"discovery": "success"}
    assert states.events == [("discovery", "running"), ("discovery", "success")]


@pytest.mark.asyncio
async def test_cancellation_after_batch_stops_later_batches_and_modules() -> None:
    cancellation = ControlledCancellation()
    adapter = MultiBatchAdapter()
    results = CancellingResults(cancellation)
    states = RecordingModuleStates()
    pipeline = CrawlPipeline(result_repository=results, module_states=states)
    context = CrawlJobContext(
        adapter=cast("object", adapter),
        adapter_context=cast(
            AdapterContext,
            SimpleNamespace(cancellation=cancellation),
        ),
        target=ResolvedTarget(
            platform="example",
            kind=TargetKind.SINGLE_VIDEO,
            canonical_url="https://example.test/video/1",
            platform_video_id="video-1",
        ),
        strategy=CrawlStrategy(),
        crawl_run_id=RUN_ID,
        video_id=11,
    )

    with pytest.raises(CancellationRequestedError):
        await pipeline.execute(context)

    assert adapter.calls == ["metrics", "comments"]
    assert len(results.comments) == 1
    assert states.events == [
        ("metrics", "running"),
        ("metrics", "success"),
        ("comments", "running"),
        ("comments", "cancelled"),
    ]


@pytest.mark.asyncio
async def test_cancellation_during_final_status_write_is_propagated() -> None:
    cancellation = ControlledCancellation()
    states = CancellingModuleStates(cancellation)
    pipeline = CrawlPipeline(
        result_repository=RecordingResults(),
        module_states=states,
        discovery_repository=RecordingDiscoveries(),
    )
    context = CrawlJobContext(
        adapter=cast("object", ListingAdapter()),
        adapter_context=cast(
            AdapterContext,
            SimpleNamespace(cancellation=cancellation),
        ),
        target=ResolvedTarget(
            platform="example",
            kind=TargetKind.VIDEO_LIST,
            canonical_url="https://example.test/popular",
        ),
        strategy=CrawlStrategy(),
        crawl_run_id=RUN_ID,
    )

    with pytest.raises(CancellationRequestedError):
        await pipeline.execute(context)

    assert states.events == [("discovery", "running"), ("discovery", "success")]


@pytest.mark.asyncio
async def test_each_streamed_batch_is_persisted_separately() -> None:
    adapter = MultiBatchAdapter()
    results = RecordingResults()
    pipeline = CrawlPipeline(
        result_repository=results,
        module_states=RecordingModuleStates(),
    )
    context = CrawlJobContext(
        adapter=cast("object", adapter),
        adapter_context=cast(
            AdapterContext,
            SimpleNamespace(cancellation=NoopCancellation()),
        ),
        target=ResolvedTarget(
            platform="example",
            kind=TargetKind.SINGLE_VIDEO,
            canonical_url="https://example.test/video/1",
            platform_video_id="video-1",
        ),
        strategy=CrawlStrategy(),
        crawl_run_id=RUN_ID,
        video_id=11,
    )

    result = await pipeline.execute(context)

    assert result.status is PipelineStatus.SUCCESS
    assert [batch.cursor for batch in results.comments] == ["page-1", None]
