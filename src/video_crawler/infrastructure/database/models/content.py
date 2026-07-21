from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from video_crawler.infrastructure.database.base import Base

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("platform_id", "platform_video_id", name="uq_video_platform_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    platform_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("platforms.id", name="fk_videos_platform"),
        nullable=False,
    )
    platform_video_id: Mapped[str] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin"), nullable=False
    )
    canonical_url: Mapped[str] = mapped_column(mysql.VARCHAR(2000), nullable=False)
    platform_ids: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
    first_discovered_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    last_crawled_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class VideoUnit(Base):
    __tablename__ = "video_units"
    __table_args__ = (
        UniqueConstraint("video_id", "platform_unit_id", name="uq_video_unit_platform_id"),
        UniqueConstraint("video_id", "unit_index", name="uq_video_unit_index"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    video_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("videos.id", name="fk_units_video"),
        nullable=False,
    )
    platform_unit_id: Mapped[str] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin"), nullable=False
    )
    unit_index: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    platform_ids: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
