from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from video_crawler.infrastructure.database.base import Base
from video_crawler.infrastructure.database.models.platforms import TABLE_OPTIONS
from video_crawler.infrastructure.database.types import UUIDBinary


class AuthProfileVerification(Base):
    __tablename__ = "auth_profile_verifications"
    __table_args__ = (
        Index("ix_profile_verifications_claim", "status", "requested_at"),
        Index("ix_profile_verifications_profile", "auth_profile_id", "requested_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True)
    auth_profile_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("auth_profiles.id", name="fk_profile_verifications_profile"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
    process_pid: Mapped[int | None] = mapped_column(mysql.INTEGER)
    process_group_id: Mapped[int | None] = mapped_column(mysql.INTEGER)
    requested_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    heartbeat_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
    error_message: Mapped[str | None] = mapped_column(mysql.TEXT)

