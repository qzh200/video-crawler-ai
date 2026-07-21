from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from video_crawler.infrastructure.database.base import Base
from video_crawler.infrastructure.database.types import UUIDBinary

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class Platform(Base):
    __tablename__ = "platforms"
    __table_args__ = (UniqueConstraint("platform_key", name="uq_platforms_key"), TABLE_OPTIONS)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    platform_key: Mapped[str] = mapped_column(mysql.VARCHAR(50), nullable=False)
    display_name: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    adapter_version: Mapped[str] = mapped_column(mysql.VARCHAR(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(mysql.BOOLEAN, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)


class AuthProfile(Base):
    __tablename__ = "auth_profiles"
    __table_args__ = (
        UniqueConstraint("platform_id", "profile_directory", name="uq_auth_profile_dir"),
        TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True)
    platform_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("platforms.id", name="fk_auth_profiles_platform"),
        nullable=False,
    )
    profile_name: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    profile_directory: Mapped[str] = mapped_column(
        mysql.VARCHAR(100, collation="utf8mb4_bin"), nullable=False
    )
    status: Mapped[str] = mapped_column(mysql.VARCHAR(20), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
