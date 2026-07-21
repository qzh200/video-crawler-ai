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


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_idempotency_key"),
        Index("ix_idempotency_expiry", "expires_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(
        mysql.VARCHAR(255, collation="utf8mb4_bin"), nullable=False
    )
    request_hash: Mapped[str] = mapped_column(mysql.CHAR(64), nullable=False)
    job_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("crawl_jobs.id", name="fk_idempotency_job"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
