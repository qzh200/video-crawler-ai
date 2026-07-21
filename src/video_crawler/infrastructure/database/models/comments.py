from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from video_crawler.infrastructure.database.base import Base

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("video_id", "platform_comment_id", name="uq_comment_platform_id"),
        Index("ix_comments_video_time", "video_id", "published_at", "id"),
        Index("ix_comments_root", "root_comment_id"),
        Index("ix_comments_parent", "parent_comment_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    video_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("videos.id", name="fk_comments_video"),
        nullable=False,
    )
    platform_comment_id: Mapped[str] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin"), nullable=False
    )
    root_platform_comment_id: Mapped[str | None] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin")
    )
    parent_platform_comment_id: Mapped[str | None] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin")
    )
    root_comment_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("comments.id", name="fk_comments_root")
    )
    parent_comment_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("comments.id", name="fk_comments_parent")
    )
    depth: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True), nullable=False)
    author_platform_id: Mapped[str | None] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin")
    )
    author_name: Mapped[str | None] = mapped_column(mysql.VARCHAR(255))
    content: Mapped[str] = mapped_column(mysql.MEDIUMTEXT, nullable=False)
    like_count: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    reply_count: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    published_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    first_seen_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
