from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint

from video_crawler.infrastructure.database import models as database_models
from video_crawler.infrastructure.database.base import Base

EXPECTED_TABLES = {
    "auth_profile_leases",
    "auth_profile_verifications",
    "auth_profiles",
    "comments",
    "crawl_jobs",
    "crawl_module_runs",
    "crawl_runs",
    "idempotency_keys",
    "metric_definitions",
    "metric_snapshots",
    "metric_values",
    "platforms",
    "raw_artifacts",
    "target_discoveries",
    "timed_text_items",
    "timed_text_streams",
    "video_units",
    "videos",
}

EXPECTED_UNIQUE_CONSTRAINTS = {
    "uq_auth_profile_dir",
    "uq_comment_platform_id",
    "uq_crawl_run_attempt",
    "uq_discovery_run_video",
    "uq_idempotency_key",
    "uq_module_run",
    "uq_platforms_key",
    "uq_raw_object",
    "uq_timed_item_dedup",
    "uq_timed_stream",
    "uq_video_platform_id",
    "uq_video_unit_index",
    "uq_video_unit_platform_id",
}

EXPECTED_INDEXES = {
    "ix_comments_parent",
    "ix_comments_root",
    "ix_comments_video_time",
    "ix_crawl_jobs_claim",
    "ix_crawl_jobs_parent",
    "ix_crawl_jobs_root",
    "ix_crawl_jobs_video",
    "ix_crawl_runs_job",
    "ix_crawl_runs_video",
    "ix_idempotency_expiry",
    "ix_metric_snapshots_video_time",
    "ix_profile_leases_expiry",
    "ix_profile_verifications_claim",
    "ix_profile_verifications_profile",
    "ix_raw_expiry",
    "ix_timed_item_cursor",
}


def test_models_register_all_reference_tables() -> None:
    assert database_models is not None
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_models_preserve_named_constraints_and_indexes() -> None:
    unique_names: set[str] = set()
    foreign_key_names: set[str] = set()
    index_names: set[str] = set()
    for table in Base.metadata.tables.values():
        unique_names.update(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint) and constraint.name is not None
        )
        foreign_key_names.update(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None
        )
        index_names.update(index.name for index in table.indexes if isinstance(index, Index))

    assert unique_names == EXPECTED_UNIQUE_CONSTRAINTS
    assert index_names == EXPECTED_INDEXES
    assert len(foreign_key_names) == 30
