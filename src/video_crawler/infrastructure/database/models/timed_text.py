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


class TimedTextStream(Base):
    __tablename__ = "timed_text_streams"
    __table_args__ = (
        UniqueConstraint(
            "video_unit_id",
            "content_type",
            "stream_key",
            "language_code_normalized",
            name="uq_timed_stream",
        ),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    video_unit_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("video_units.id", name="fk_timed_stream_unit"),
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    stream_key: Mapped[str] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin"), nullable=False
    )
    language_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(30))
    language_code_normalized: Mapped[str] = mapped_column(
        mysql.VARCHAR(30, collation="utf8mb4_bin"), nullable=False, server_default=""
    )
    source_type: Mapped[str] = mapped_column(mysql.VARCHAR(30), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    raw_artifact_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("raw_artifacts.id", name="fk_timed_stream_raw"),
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class TimedTextItem(Base):
    __tablename__ = "timed_text_items"
    __table_args__ = (
        UniqueConstraint("stream_id", "dedup_key", name="uq_timed_item_dedup"),
        Index("ix_timed_item_cursor", "stream_id", "start_ms", "id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("timed_text_streams.id", name="fk_timed_item_stream"),
        nullable=False,
    )
    platform_item_id: Mapped[str | None] = mapped_column(
        mysql.VARCHAR(200, collation="utf8mb4_bin")
    )
    dedup_key: Mapped[str] = mapped_column(mysql.CHAR(64), nullable=False)
    start_ms: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    end_ms: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    text: Mapped[str] = mapped_column(mysql.MEDIUMTEXT, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    sender_ref: Mapped[str | None] = mapped_column(mysql.VARCHAR(200))
    attributes: Mapped[dict[str, Any]] = mapped_column(mysql.JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
