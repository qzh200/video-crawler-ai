from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from video_crawler.adapters.base import AdapterContext, VideoSiteAdapter
from video_crawler.application.module_runner import (
    ModuleRunner,
    ModuleStateStore,
    ModuleStatus,
)
from video_crawler.domain.comments import CommentBatch
from video_crawler.domain.metrics import MetricResult
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import DiscoveredTarget, ResolvedTarget, TargetKind, VideoTarget
from video_crawler.domain.timed_text import TimedTextBatch


class PipelineStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ResultRepository(Protocol):
    async def create_metric_snapshot(
        self,
        video_id: int,
        crawl_run_id: UUID,
        result: MetricResult,
    ) -> int: ...

    async def upsert_comments(self, video_id: int, batch: CommentBatch) -> int: ...

    async def upsert_timed_text_batch(self, video_id: int, batch: TimedTextBatch) -> int: ...


class DiscoveryRepository(Protocol):
    """Persist a discovered target through the application-level discovery workflow.

    A production implementation composes content and job repositories so recording a
    target can upsert its generic video identity and ensure its child crawl job.
    """

    async def record_discovered_target(
        self,
        crawl_run_id: UUID,
        target: DiscoveredTarget,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CrawlJobContext:
    adapter: VideoSiteAdapter
    adapter_context: AdapterContext
    target: ResolvedTarget
    strategy: CrawlStrategy
    crawl_run_id: UUID
    video_id: int | None = None
    prior_module_states: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    status: PipelineStatus
    module_states: Mapping[str, str]


class CrawlPipeline:
    def __init__(
        self,
        *,
        result_repository: ResultRepository,
        module_states: ModuleStateStore,
        discovery_repository: DiscoveryRepository | None = None,
    ) -> None:
        self._results = result_repository
        self._runner = ModuleRunner(module_states)
        self._discoveries = discovery_repository

    async def execute(self, job_context: CrawlJobContext) -> PipelineResult:
        if job_context.target.kind is TargetKind.VIDEO_LIST:
            return await self._execute_discovery(job_context)
        if job_context.video_id is None or job_context.target.platform_video_id is None:
            raise ValueError("video target requires video_id and platform_video_id")

        video_id = job_context.video_id
        target = VideoTarget(
            platform=job_context.target.platform,
            platform_video_id=job_context.target.platform_video_id,
            canonical_url=job_context.target.canonical_url,
            platform_ids=job_context.target.platform_ids,
        )
        cancellation = job_context.adapter_context.cancellation

        async def store_metrics() -> None:
            result = await job_context.adapter.fetch_metrics(job_context.adapter_context, target)
            await self._results.create_metric_snapshot(
                video_id,
                job_context.crawl_run_id,
                result,
            )

        async def store_comments() -> None:
            async for batch in job_context.adapter.fetch_comments(
                job_context.adapter_context,
                target,
                job_context.strategy,
            ):
                cancellation.raise_if_cancelled()
                await self._results.upsert_comments(video_id, batch)
                cancellation.raise_if_cancelled()

        async def store_timed_text() -> None:
            async for batch in job_context.adapter.fetch_timed_text(
                job_context.adapter_context,
                target,
                job_context.strategy,
            ):
                cancellation.raise_if_cancelled()
                await self._results.upsert_timed_text_batch(video_id, batch)
                cancellation.raise_if_cancelled()

        operations = (
            ("metrics", store_metrics),
            ("comments", store_comments),
            ("timed_text", store_timed_text),
        )
        module_results = []
        for module_key, operation in operations:
            if job_context.prior_module_states.get(module_key) == ModuleStatus.SUCCESS.value:
                module_results.append(await self._runner.skip(module_key, cancellation))
            else:
                module_results.append(await self._runner.run(module_key, operation, cancellation))
        states = {result.module_key: result.status.value for result in module_results}
        successful = sum(
            result.status in {ModuleStatus.SUCCESS, ModuleStatus.SKIPPED}
            for result in module_results
        )
        failed = sum(result.status is ModuleStatus.FAILED for result in module_results)
        if failed == 0:
            status = PipelineStatus.SUCCESS
        elif successful == 0:
            status = PipelineStatus.FAILED
        else:
            status = PipelineStatus.PARTIAL
        return PipelineResult(status=status, module_states=states)

    async def _execute_discovery(self, job_context: CrawlJobContext) -> PipelineResult:
        if self._discoveries is None:
            raise ValueError("list target requires a discovery repository")
        discoveries = self._discoveries
        cancellation = job_context.adapter_context.cancellation

        async def store_discoveries() -> None:
            async for target in job_context.adapter.discover_targets(
                job_context.adapter_context,
                job_context.target,
                job_context.strategy,
            ):
                cancellation.raise_if_cancelled()
                await discoveries.record_discovered_target(
                    job_context.crawl_run_id,
                    target,
                )
                cancellation.raise_if_cancelled()

        if job_context.prior_module_states.get("discovery") == ModuleStatus.SUCCESS.value:
            result = await self._runner.skip("discovery", cancellation)
        else:
            result = await self._runner.run("discovery", store_discoveries, cancellation)
        status = (
            PipelineStatus.FAILED
            if result.status is ModuleStatus.FAILED
            else PipelineStatus.SUCCESS
        )
        return PipelineResult(
            status=status,
            module_states={result.module_key: result.status.value},
        )
