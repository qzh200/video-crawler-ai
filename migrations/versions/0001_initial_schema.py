from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

METRIC_DEFINITIONS = (
    ("standard.views", "Views", "standard"),
    ("standard.likes", "Likes", "standard"),
    ("standard.favorites", "Favorites", "standard"),
    ("standard.shares", "Shares", "standard"),
    ("standard.comments", "Comments", "standard"),
    ("standard.timed_comments", "Timed comments", "standard"),
    ("bilibili.coins", "Coins", "bilibili"),
)


def upgrade() -> None:
    op.create_table(
        "platforms",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("platform_key", mysql.VARCHAR(50), nullable=False),
        sa.Column("display_name", mysql.VARCHAR(100), nullable=False),
        sa.Column("adapter_version", mysql.VARCHAR(50), nullable=False),
        sa.Column("enabled", mysql.TINYINT(display_width=1), server_default="1", nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_key", name="uq_platforms_key"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "auth_profiles",
        sa.Column("id", sa.BINARY(16), nullable=False),
        sa.Column("platform_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("profile_name", mysql.VARCHAR(100), nullable=False),
        sa.Column(
            "profile_directory",
            mysql.VARCHAR(100, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("last_verified_at", mysql.DATETIME(fsp=3)),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["platform_id"], ["platforms.id"], name="fk_auth_profiles_platform"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_id", "profile_directory", name="uq_auth_profile_dir"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "videos",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("platform_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "platform_video_id",
            mysql.VARCHAR(200, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column("canonical_url", mysql.VARCHAR(2000), nullable=False),
        sa.Column("platform_ids", mysql.JSON, nullable=False),
        sa.Column("first_discovered_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("last_crawled_at", mysql.DATETIME(fsp=3)),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], name="fk_videos_platform"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_id", "platform_video_id", name="uq_video_platform_id"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.BINARY(16), nullable=False),
        sa.Column("parent_job_id", sa.BINARY(16)),
        sa.Column("root_job_id", sa.BINARY(16), nullable=False),
        sa.Column("platform_id", mysql.BIGINT(unsigned=True)),
        sa.Column("auth_profile_id", sa.BINARY(16), nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True)),
        sa.Column("source_url", mysql.VARCHAR(2000), nullable=False),
        sa.Column("job_type", mysql.VARCHAR(30), nullable=False),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("priority", mysql.INTEGER, server_default="0", nullable=False),
        sa.Column(
            "strategy_version", mysql.INTEGER(unsigned=True), server_default="1", nullable=False
        ),
        sa.Column("effective_strategy", mysql.JSON, nullable=False),
        sa.Column(
            "cancel_requested", mysql.TINYINT(display_width=1), server_default="0", nullable=False
        ),
        sa.Column("cancel_requested_at", mysql.DATETIME(fsp=3)),
        sa.Column("cancelled_at", mysql.DATETIME(fsp=3)),
        sa.Column("cancel_reason", mysql.VARCHAR(500)),
        sa.Column(
            "attempt_count", mysql.INTEGER(unsigned=True), server_default="0", nullable=False
        ),
        sa.Column("max_attempts", mysql.INTEGER(unsigned=True), server_default="3", nullable=False),
        sa.Column("next_retry_at", mysql.DATETIME(fsp=3)),
        sa.Column("locked_by", mysql.VARCHAR(100)),
        sa.Column("locked_at", mysql.DATETIME(fsp=3)),
        sa.Column("heartbeat_at", mysql.DATETIME(fsp=3)),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["parent_job_id"], ["crawl_jobs.id"], name="fk_jobs_parent"),
        sa.ForeignKeyConstraint(["root_job_id"], ["crawl_jobs.id"], name="fk_jobs_root"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], name="fk_jobs_platform"),
        sa.ForeignKeyConstraint(["auth_profile_id"], ["auth_profiles.id"], name="fk_jobs_profile"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_jobs_video"),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_crawl_jobs_claim", "crawl_jobs", ["status", "priority", "created_at"])
    op.create_index("ix_crawl_jobs_parent", "crawl_jobs", ["parent_job_id"])
    op.create_index("ix_crawl_jobs_root", "crawl_jobs", ["root_job_id"])
    op.create_index("ix_crawl_jobs_video", "crawl_jobs", ["video_id"])
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BINARY(16), nullable=False),
        sa.Column("job_id", sa.BINARY(16), nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True)),
        sa.Column("attempt_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("worker_id", mysql.VARCHAR(100), nullable=False),
        sa.Column("adapter_version", mysql.VARCHAR(50)),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("process_pid", mysql.INTEGER),
        sa.Column("process_group_id", mysql.INTEGER),
        sa.Column("termination_signal", mysql.VARCHAR(20)),
        sa.Column("started_at", mysql.DATETIME(fsp=3)),
        sa.Column("finished_at", mysql.DATETIME(fsp=3)),
        sa.Column("heartbeat_at", mysql.DATETIME(fsp=3)),
        sa.Column("terminated_at", mysql.DATETIME(fsp=3)),
        sa.Column("error_code", mysql.VARCHAR(100)),
        sa.Column("error_message", mysql.TEXT),
        sa.Column("result_summary", mysql.JSON),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["crawl_jobs.id"], name="fk_runs_job"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_runs_video"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_crawl_run_attempt"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_crawl_runs_job", "crawl_runs", ["job_id", "created_at"])
    op.create_index("ix_crawl_runs_video", "crawl_runs", ["video_id"])
    op.create_table(
        "crawl_module_runs",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("crawl_run_id", sa.BINARY(16), nullable=False),
        sa.Column("module_key", mysql.VARCHAR(30), nullable=False),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=3)),
        sa.Column("finished_at", mysql.DATETIME(fsp=3)),
        sa.Column("error_code", mysql.VARCHAR(100)),
        sa.Column("error_message", mysql.TEXT),
        sa.Column("result_summary", mysql.JSON),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], name="fk_module_runs_run"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "module_key", name="uq_module_run"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "auth_profile_leases",
        sa.Column("auth_profile_id", sa.BINARY(16), nullable=False),
        sa.Column("worker_id", mysql.VARCHAR(100), nullable=False),
        sa.Column("crawl_run_id", sa.BINARY(16), nullable=False),
        sa.Column("process_pid", mysql.INTEGER),
        sa.Column("acquired_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("heartbeat_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["auth_profile_id"], ["auth_profiles.id"], name="fk_lease_profile"),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], name="fk_lease_run"),
        sa.PrimaryKeyConstraint("auth_profile_id"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_profile_leases_expiry", "auth_profile_leases", ["expires_at"])
    op.create_table(
        "video_units",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("platform_unit_id", mysql.VARCHAR(200, collation="utf8mb4_bin"), nullable=False),
        sa.Column("unit_index", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("duration_ms", mysql.BIGINT(unsigned=True)),
        sa.Column("platform_ids", mysql.JSON, nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_units_video"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "platform_unit_id", name="uq_video_unit_platform_id"),
        sa.UniqueConstraint("video_id", "unit_index", name="uq_video_unit_index"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "target_discoveries",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("crawl_run_id", sa.BINARY(16), nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("source_url", mysql.VARCHAR(2000), nullable=False),
        sa.Column("position", mysql.INTEGER(unsigned=True)),
        sa.Column("discovered_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], name="fk_discovery_run"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_discovery_video"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "video_id", name="uq_discovery_run_video"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "metric_definitions",
        sa.Column("metric_key", mysql.VARCHAR(100, collation="utf8mb4_bin"), nullable=False),
        sa.Column("display_name", mysql.VARCHAR(100), nullable=False),
        sa.Column("namespace", mysql.VARCHAR(50), nullable=False),
        sa.Column("description", mysql.VARCHAR(500)),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.PrimaryKeyConstraint("metric_key"),
        **TABLE_OPTIONS,
    )
    _seed_metric_definitions()
    op.create_table(
        "raw_artifacts",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("crawl_run_id", sa.BINARY(16), nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True)),
        sa.Column("artifact_type", mysql.VARCHAR(50), nullable=False),
        sa.Column("bucket", mysql.VARCHAR(100), nullable=False),
        sa.Column("object_key", mysql.VARCHAR(600), nullable=False),
        sa.Column("content_type", mysql.VARCHAR(200), nullable=False),
        sa.Column("compression", mysql.VARCHAR(20), nullable=False),
        sa.Column("etag", mysql.VARCHAR(200)),
        sa.Column("sha256", mysql.CHAR(64)),
        sa.Column("size_bytes", mysql.BIGINT(unsigned=True)),
        sa.Column("storage_status", mysql.VARCHAR(20), nullable=False),
        sa.Column("captured_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=3)),
        sa.Column("deleted_at", mysql.DATETIME(fsp=3)),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], name="fk_raw_run"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_raw_video"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket", "object_key", name="uq_raw_object"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_raw_expiry", "raw_artifacts", ["storage_status", "expires_at"])
    op.create_table(
        "metric_snapshots",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("crawl_run_id", sa.BINARY(16), nullable=False),
        sa.Column("captured_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("snapshot_hash", mysql.CHAR(64), nullable=False),
        sa.Column("raw_artifact_id", mysql.BIGINT(unsigned=True)),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_metric_snapshot_video"),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], name="fk_metric_snapshot_run"),
        sa.ForeignKeyConstraint(
            ["raw_artifact_id"], ["raw_artifacts.id"], name="fk_metric_snapshot_raw"
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_metric_snapshots_video_time", "metric_snapshots", ["video_id", "captured_at", "id"]
    )
    op.create_table(
        "metric_values",
        sa.Column("snapshot_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("metric_key", mysql.VARCHAR(100, collation="utf8mb4_bin"), nullable=False),
        sa.Column("metric_value", mysql.BIGINT(unsigned=True)),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("source_path", mysql.VARCHAR(500)),
        sa.Column("extra", mysql.JSON, nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["metric_snapshots.id"], name="fk_metric_value_snapshot"
        ),
        sa.ForeignKeyConstraint(
            ["metric_key"],
            ["metric_definitions.metric_key"],
            name="fk_metric_value_definition",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "metric_key"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "comments",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("video_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "platform_comment_id",
            mysql.VARCHAR(200, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column("root_platform_comment_id", mysql.VARCHAR(200, collation="utf8mb4_bin")),
        sa.Column("parent_platform_comment_id", mysql.VARCHAR(200, collation="utf8mb4_bin")),
        sa.Column("root_comment_id", mysql.BIGINT(unsigned=True)),
        sa.Column("parent_comment_id", mysql.BIGINT(unsigned=True)),
        sa.Column("depth", mysql.SMALLINT(unsigned=True), nullable=False),
        sa.Column("author_platform_id", mysql.VARCHAR(200, collation="utf8mb4_bin")),
        sa.Column("author_name", mysql.VARCHAR(255)),
        sa.Column("content", mysql.MEDIUMTEXT, nullable=False),
        sa.Column("like_count", mysql.BIGINT(unsigned=True)),
        sa.Column("reply_count", mysql.BIGINT(unsigned=True)),
        sa.Column("published_at", mysql.DATETIME(fsp=3)),
        sa.Column("first_seen_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("last_seen_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("extra", mysql.JSON, nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name="fk_comments_video"),
        sa.ForeignKeyConstraint(["root_comment_id"], ["comments.id"], name="fk_comments_root"),
        sa.ForeignKeyConstraint(["parent_comment_id"], ["comments.id"], name="fk_comments_parent"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "platform_comment_id", name="uq_comment_platform_id"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_comments_video_time", "comments", ["video_id", "published_at", "id"])
    op.create_index("ix_comments_root", "comments", ["root_comment_id"])
    op.create_index("ix_comments_parent", "comments", ["parent_comment_id"])
    op.create_table(
        "timed_text_streams",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("video_unit_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("content_type", mysql.VARCHAR(20), nullable=False),
        sa.Column("stream_key", mysql.VARCHAR(200, collation="utf8mb4_bin"), nullable=False),
        sa.Column("language_code", mysql.VARCHAR(30)),
        sa.Column(
            "language_code_normalized",
            mysql.VARCHAR(30, collation="utf8mb4_bin"),
            server_default="",
            nullable=False,
        ),
        sa.Column("source_type", mysql.VARCHAR(30), nullable=False),
        sa.Column("captured_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("raw_artifact_id", mysql.BIGINT(unsigned=True)),
        sa.Column("attributes", mysql.JSON, nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["video_unit_id"], ["video_units.id"], name="fk_timed_stream_unit"),
        sa.ForeignKeyConstraint(
            ["raw_artifact_id"], ["raw_artifacts.id"], name="fk_timed_stream_raw"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "video_unit_id",
            "content_type",
            "stream_key",
            "language_code_normalized",
            name="uq_timed_stream",
        ),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "timed_text_items",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("stream_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("platform_item_id", mysql.VARCHAR(200, collation="utf8mb4_bin")),
        sa.Column("dedup_key", mysql.CHAR(64), nullable=False),
        sa.Column("start_ms", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("end_ms", mysql.BIGINT(unsigned=True)),
        sa.Column("text", mysql.MEDIUMTEXT, nullable=False),
        sa.Column("published_at", mysql.DATETIME(fsp=3)),
        sa.Column("sender_ref", mysql.VARCHAR(200)),
        sa.Column("attributes", mysql.JSON, nullable=False),
        sa.Column("first_seen_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("last_seen_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["stream_id"], ["timed_text_streams.id"], name="fk_timed_item_stream"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stream_id", "dedup_key", name="uq_timed_item_dedup"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_timed_item_cursor", "timed_text_items", ["stream_id", "start_ms", "id"])
    op.create_table(
        "idempotency_keys",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("idempotency_key", mysql.VARCHAR(255, collation="utf8mb4_bin"), nullable=False),
        sa.Column("request_hash", mysql.CHAR(64), nullable=False),
        sa.Column("job_id", sa.BINARY(16), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["crawl_jobs.id"], name="fk_idempotency_job"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_idempotency_key"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_idempotency_expiry", "idempotency_keys", ["expires_at"])


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("timed_text_items")
    op.drop_table("timed_text_streams")
    op.drop_table("comments")
    op.drop_table("metric_values")
    op.drop_table("metric_snapshots")
    op.drop_table("raw_artifacts")
    _delete_metric_definitions()
    op.drop_table("metric_definitions")
    op.drop_table("target_discoveries")
    op.drop_table("video_units")
    op.drop_table("auth_profile_leases")
    op.drop_table("crawl_module_runs")
    op.drop_table("crawl_runs")
    op.drop_table("crawl_jobs")
    op.drop_table("videos")
    op.drop_table("auth_profiles")
    op.drop_table("platforms")


def _seed_metric_definitions() -> None:
    metric_definitions = sa.table(
        "metric_definitions",
        sa.column("metric_key", sa.String),
        sa.column("display_name", sa.String),
        sa.column("namespace", sa.String),
        sa.column("description", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    created_at = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        metric_definitions,
        [
            {
                "metric_key": metric_key,
                "display_name": display_name,
                "namespace": namespace,
                "description": None,
                "created_at": created_at,
            }
            for metric_key, display_name, namespace in METRIC_DEFINITIONS
        ],
    )


def _delete_metric_definitions() -> None:
    metric_definitions = sa.table(
        "metric_definitions",
        sa.column("metric_key", sa.String),
    )
    keys = [metric_key for metric_key, _, _ in METRIC_DEFINITIONS]
    op.execute(metric_definitions.delete().where(metric_definitions.c.metric_key.in_(keys)))
