from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from video_crawler.application.jobs import JobRecord


class StrategyOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_root_comments: int | None = Field(default=None, ge=0, le=100_000)
    fetch_all_replies: bool | None = None
    fetch_all_danmaku: bool | None = None
    fetch_all_subtitles: bool | None = None
    timed_text_batch_size: int | None = Field(default=None, ge=100, le=5000)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    video_delay_min_seconds: float | None = Field(default=None, ge=0.5)
    video_delay_max_seconds: float | None = Field(default=None, ge=0.5)
    comment_page_delay_min_seconds: float | None = Field(default=None, ge=0.5)
    comment_page_delay_max_seconds: float | None = Field(default=None, ge=0.5)
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    page_timeout_seconds: int | None = Field(default=None, ge=10, le=300)

    @model_validator(mode="after")
    def validate_delay_order(self) -> Self:
        if (
            self.video_delay_min_seconds is not None
            and self.video_delay_max_seconds is not None
            and self.video_delay_min_seconds > self.video_delay_max_seconds
        ):
            raise ValueError("video delay min must not exceed video delay max")
        if (
            self.comment_page_delay_min_seconds is not None
            and self.comment_page_delay_max_seconds is not None
            and self.comment_page_delay_min_seconds > self.comment_page_delay_max_seconds
        ):
            raise ValueError("comment page delay min must not exceed comment page delay max")
        return self

    def defined_values(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class CrawlJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: HttpUrl
    auth_profile_id: UUID
    video_limit: int | None = Field(default=None, ge=1, le=500)
    strategy: StrategyOverrides = Field(default_factory=StrategyOverrides)


class CrawlJobResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: StrategyOverrides = Field(default_factory=StrategyOverrides)


class CrawlJobResponse(BaseModel):
    job_id: UUID
    auth_profile_id: UUID
    source_url: str
    status: str
    strategy_version: int
    effective_strategy: dict[str, object]
    root_job_id: UUID
    parent_job_id: UUID | None
    progress: dict[str, object]
    module_states: dict[str, str]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: dict[str, object] | None

    @classmethod
    def from_record(cls, record: JobRecord) -> CrawlJobResponse:
        return cls(
            job_id=record.id,
            auth_profile_id=record.auth_profile_id,
            source_url=record.source_url,
            status=record.status,
            strategy_version=record.strategy_version,
            effective_strategy=record.effective_strategy,
            root_job_id=record.root_job_id,
            parent_job_id=record.parent_job_id,
            progress=record.progress,
            module_states=record.module_states,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            error=record.error,
        )
