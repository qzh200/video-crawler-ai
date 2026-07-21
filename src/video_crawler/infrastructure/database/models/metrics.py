from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from video_crawler.infrastructure.database.base import Base
from video_crawler.infrastructure.database.types import UUIDBinary

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (TABLE_OPTIONS,)

    metric_key: Mapped[str] = mapped_column(
        mysql.VARCHAR(100, collation="utf8mb4_bin"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    namespace: Mapped[str] = mapped_column(mysql.VARCHAR(50), nullable=False)
    description: Mapped[str | None] = mapped_column(mysql.VARCHAR(500))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        Index("ix_metric_snapshots_video_time", "video_id", "captured_at", "id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    video_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("videos.id", name="fk_metric_snapshot_video"),
        nullable=False,
    )
    crawl_run_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_runs.id", name="fk_metric_snapshot_run"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(mysql.CHAR(64), nullable=False)
    raw_artifact_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("raw_artifacts.id", name="fk_metric_snapshot_raw"),
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class MetricValue(Base):
    __tablename__ = "metric_values"
    __table_args__ = (TABLE_OPTIONS,)

    snapshot_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("metric_snapshots.id", name="fk_metric_value_snapshot"),
        primary_key=True,
    )
    metric_key: Mapped[str] = mapped_column(
        mysql.VARCHAR(100, collation="utf8mb4_bin"),
        ForeignKey("metric_definitions.metric_key", name="fk_metric_value_definition"),
        primary_key=True,
    )
    metric_value: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    source_path: Mapped[str | None] = mapped_column(mysql.VARCHAR(500))
    extra: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
