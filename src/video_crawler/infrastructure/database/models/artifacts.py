from __future__ import annotations

from datetime import datetime
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


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_raw_object"),
        Index("ix_raw_expiry", "storage_status", "expires_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    crawl_run_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_runs.id", name="fk_raw_run"), nullable=False
    )
    video_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("videos.id", name="fk_raw_video")
    )
    artifact_type: Mapped[str] = mapped_column(mysql.VARCHAR(50), nullable=False)
    bucket: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    object_key: Mapped[str] = mapped_column(mysql.VARCHAR(600), nullable=False)
    content_type: Mapped[str] = mapped_column(mysql.VARCHAR(200), nullable=False)
    compression: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    etag: Mapped[str | None] = mapped_column(mysql.VARCHAR(200))
    sha256: Mapped[str | None] = mapped_column(mysql.CHAR(64))
    size_bytes: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    storage_status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    deleted_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
