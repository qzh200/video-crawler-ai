from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from video_crawler.infrastructure.database.base import Base
from video_crawler.infrastructure.database.types import UUIDBinary

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index("ix_crawl_jobs_claim", "status", "priority", "created_at"),
        Index("ix_crawl_jobs_parent", "parent_job_id"),
        Index("ix_crawl_jobs_root", "root_job_id"),
        Index("ix_crawl_jobs_video", "video_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True)
    parent_job_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_jobs.id", name="fk_jobs_parent")
    )
    root_job_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_jobs.id", name="fk_jobs_root"), nullable=False
    )
    platform_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("platforms.id", name="fk_jobs_platform")
    )
    auth_profile_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("auth_profiles.id", name="fk_jobs_profile"), nullable=False
    )
    video_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("videos.id", name="fk_jobs_video")
    )
    source_url: Mapped[str] = mapped_column(mysql.VARCHAR(2000), nullable=False)
    job_type: Mapped[str] = mapped_column(mysql.VARCHAR(30), nullable=False)
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    priority: Mapped[int] = mapped_column(mysql.INTEGER, nullable=False, server_default="0")
    strategy_version: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, server_default="1"
    )
    effective_strategy: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(
        mysql.BOOLEAN, nullable=False, server_default="0"
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    cancelled_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    cancel_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(500))
    attempt_count: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, server_default="3"
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    locked_by: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
    locked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    heartbeat_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no", name="uq_crawl_run_attempt"),
        Index("ix_crawl_runs_job", "job_id", "created_at"),
        Index("ix_crawl_runs_video", "video_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_jobs.id", name="fk_runs_job"), nullable=False
    )
    video_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("videos.id", name="fk_runs_video")
    )
    attempt_no: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    worker_id: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(mysql.VARCHAR(50))
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    process_pid: Mapped[int | None] = mapped_column(mysql.INTEGER)
    process_group_id: Mapped[int | None] = mapped_column(mysql.INTEGER)
    termination_signal: Mapped[str | None] = mapped_column(mysql.VARCHAR(20))
    started_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    heartbeat_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    terminated_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
    error_message: Mapped[str | None] = mapped_column(mysql.TEXT)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(mysql.JSON)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class CrawlModuleRun(Base):
    __tablename__ = "crawl_module_runs"
    __table_args__ = (
        UniqueConstraint("crawl_run_id", "module_key", name="uq_module_run"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    crawl_run_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_runs.id", name="fk_module_runs_run"), nullable=False
    )
    module_key: Mapped[str] = mapped_column(mysql.VARCHAR(30), nullable=False)
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
    error_message: Mapped[str | None] = mapped_column(mysql.TEXT)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(mysql.JSON)


class AuthProfileLease(Base):
    __tablename__ = "auth_profile_leases"
    __table_args__ = (Index("ix_profile_leases_expiry", "expires_at"), TABLE_OPTIONS)

    auth_profile_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("auth_profiles.id", name="fk_lease_profile"),
        primary_key=True,
    )
    worker_id: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    crawl_run_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_runs.id", name="fk_lease_run"), nullable=False
    )
    process_pid: Mapped[int | None] = mapped_column(mysql.INTEGER)
    acquired_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class TargetDiscovery(Base):
    __tablename__ = "target_discoveries"
    __table_args__ = (
        UniqueConstraint("crawl_run_id", "video_id", name="uq_discovery_run_video"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    crawl_run_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_runs.id", name="fk_discovery_run"), nullable=False
    )
    video_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("videos.id", name="fk_discovery_video"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(mysql.VARCHAR(2000), nullable=False)
    position: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True))
    discovered_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
