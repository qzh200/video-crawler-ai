from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"  # noqa: S104 - container API must accept external traffic
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    api_key_enabled: bool = True
    api_key: SecretStr

    mysql_host: str = "mysql"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = "video_crawler"
    mysql_user: str = "video_crawler"
    mysql_password: SecretStr
    mysql_pool_size: int = Field(default=10, ge=1)
    mysql_max_overflow: int = Field(default=10, ge=0)

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "video-crawler"
    minio_secret_key: SecretStr
    minio_bucket: str = "crawler-raw"
    minio_secure: bool = False

    raw_artifact_retention_days: int = Field(default=30, ge=0, le=3650)
    raw_artifact_cleanup_enabled: bool = True
    raw_artifact_cleanup_hour_utc: int = Field(default=3, ge=0, le=23)

    browser_profile_root: Path = Path("/var/lib/video-crawler/browser-profiles")
    worker_id: str = "worker-1"
    worker_poll_interval_seconds: float = Field(default=2.0, gt=0)
    worker_heartbeat_interval_seconds: float = Field(default=5.0, gt=0)
    worker_stale_after_seconds: float = Field(default=30.0, gt=0)
    worker_concurrency: Literal[1] = 1
    profile_concurrency: Literal[1] = 1
    task_terminate_grace_seconds: int = Field(default=5, ge=1, le=30)
    task_kill_timeout_seconds: float = Field(default=10.0, gt=0)

    default_video_limit: int = Field(default=100, ge=1, le=500)
    default_max_root_comments: int = Field(default=1000, ge=0, le=100_000)
    default_fetch_all_replies: bool = True
    default_fetch_all_danmaku: bool = True
    default_fetch_all_subtitles: bool = True
    default_timed_text_batch_size: int = Field(default=1000, ge=100, le=5000)
    default_max_retries: int = Field(default=3, ge=0, le=5)
    default_video_delay_min_seconds: float = Field(default=1.0, ge=0.5)
    default_video_delay_max_seconds: float = Field(default=3.0, ge=0.5)
    default_comment_page_delay_min_seconds: float = Field(default=0.8, ge=0.5)
    default_comment_page_delay_max_seconds: float = Field(default=1.5, ge=0.5)
    default_request_timeout_seconds: int = Field(default=30, ge=5, le=120)
    default_page_timeout_seconds: int = Field(default=60, ge=10, le=300)

    idempotency_ttl_hours: int = Field(default=24, ge=1)

    @model_validator(mode="after")
    def validate_delay_ranges(self) -> Self:
        if self.default_video_delay_min_seconds > self.default_video_delay_max_seconds:
            raise ValueError("video delay min must not exceed video delay max")
        if (
            self.default_comment_page_delay_min_seconds
            > self.default_comment_page_delay_max_seconds
        ):
            raise ValueError("comment page delay min must not exceed comment page delay max")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()
