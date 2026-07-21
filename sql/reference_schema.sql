-- Reference schema only. Alembic migrations are authoritative.
CREATE DATABASE IF NOT EXISTS video_crawler
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE video_crawler;

CREATE TABLE platforms (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  platform_key VARCHAR(50) NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  adapter_version VARCHAR(50) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_platforms_key (platform_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE auth_profiles (
  id BINARY(16) NOT NULL,
  platform_id BIGINT UNSIGNED NOT NULL,
  profile_name VARCHAR(100) NOT NULL,
  profile_directory VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  status VARCHAR(20) NOT NULL,
  last_verified_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_auth_profile_dir (platform_id, profile_directory),
  CONSTRAINT fk_auth_profiles_platform FOREIGN KEY (platform_id) REFERENCES platforms(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE crawl_jobs (
  id BINARY(16) NOT NULL,
  parent_job_id BINARY(16) NULL,
  root_job_id BINARY(16) NOT NULL,
  platform_id BIGINT UNSIGNED NULL,
  auth_profile_id BINARY(16) NOT NULL,
  video_id BIGINT UNSIGNED NULL,
  source_url VARCHAR(2000) NOT NULL,
  job_type VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL,
  priority INT NOT NULL DEFAULT 0,
  strategy_version INT UNSIGNED NOT NULL DEFAULT 1,
  effective_strategy JSON NOT NULL,
  cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
  cancel_requested_at DATETIME(3) NULL,
  cancelled_at DATETIME(3) NULL,
  cancel_reason VARCHAR(500) NULL,
  attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
  max_attempts INT UNSIGNED NOT NULL DEFAULT 3,
  next_retry_at DATETIME(3) NULL,
  locked_by VARCHAR(100) NULL,
  locked_at DATETIME(3) NULL,
  heartbeat_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_crawl_jobs_claim (status, priority, created_at),
  KEY ix_crawl_jobs_parent (parent_job_id),
  KEY ix_crawl_jobs_root (root_job_id),
  KEY ix_crawl_jobs_video (video_id),
  CONSTRAINT fk_jobs_parent FOREIGN KEY (parent_job_id) REFERENCES crawl_jobs(id),
  CONSTRAINT fk_jobs_root FOREIGN KEY (root_job_id) REFERENCES crawl_jobs(id),
  CONSTRAINT fk_jobs_platform FOREIGN KEY (platform_id) REFERENCES platforms(id),
  CONSTRAINT fk_jobs_profile FOREIGN KEY (auth_profile_id) REFERENCES auth_profiles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE crawl_runs (
  id BINARY(16) NOT NULL,
  job_id BINARY(16) NOT NULL,
  video_id BIGINT UNSIGNED NULL,
  attempt_no INT UNSIGNED NOT NULL,
  worker_id VARCHAR(100) NOT NULL,
  adapter_version VARCHAR(50) NULL,
  status VARCHAR(20) NOT NULL,
  process_pid INT NULL,
  process_group_id INT NULL,
  termination_signal VARCHAR(20) NULL,
  started_at DATETIME(3) NULL,
  finished_at DATETIME(3) NULL,
  heartbeat_at DATETIME(3) NULL,
  terminated_at DATETIME(3) NULL,
  error_code VARCHAR(100) NULL,
  error_message TEXT NULL,
  result_summary JSON NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_crawl_run_attempt (job_id, attempt_no),
  KEY ix_crawl_runs_job (job_id, created_at),
  KEY ix_crawl_runs_video (video_id),
  CONSTRAINT fk_runs_job FOREIGN KEY (job_id) REFERENCES crawl_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE crawl_module_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  crawl_run_id BINARY(16) NOT NULL,
  module_key VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL,
  started_at DATETIME(3) NULL,
  finished_at DATETIME(3) NULL,
  error_code VARCHAR(100) NULL,
  error_message TEXT NULL,
  result_summary JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_module_run (crawl_run_id, module_key),
  CONSTRAINT fk_module_runs_run FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE auth_profile_leases (
  auth_profile_id BINARY(16) NOT NULL,
  worker_id VARCHAR(100) NOT NULL,
  crawl_run_id BINARY(16) NOT NULL,
  process_pid INT NULL,
  acquired_at DATETIME(3) NOT NULL,
  heartbeat_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  PRIMARY KEY (auth_profile_id),
  KEY ix_profile_leases_expiry (expires_at),
  CONSTRAINT fk_lease_profile FOREIGN KEY (auth_profile_id) REFERENCES auth_profiles(id),
  CONSTRAINT fk_lease_run FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE videos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  platform_id BIGINT UNSIGNED NOT NULL,
  platform_video_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  canonical_url VARCHAR(2000) NOT NULL,
  platform_ids JSON NOT NULL,
  first_discovered_at DATETIME(3) NOT NULL,
  last_crawled_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_video_platform_id (platform_id, platform_video_id),
  CONSTRAINT fk_videos_platform FOREIGN KEY (platform_id) REFERENCES platforms(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE crawl_jobs
  ADD CONSTRAINT fk_jobs_video FOREIGN KEY (video_id) REFERENCES videos(id);

ALTER TABLE crawl_runs
  ADD CONSTRAINT fk_runs_video FOREIGN KEY (video_id) REFERENCES videos(id);

CREATE TABLE video_units (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  video_id BIGINT UNSIGNED NOT NULL,
  platform_unit_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  unit_index INT UNSIGNED NOT NULL,
  duration_ms BIGINT UNSIGNED NULL,
  platform_ids JSON NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_video_unit_platform_id (video_id, platform_unit_id),
  UNIQUE KEY uq_video_unit_index (video_id, unit_index),
  CONSTRAINT fk_units_video FOREIGN KEY (video_id) REFERENCES videos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE target_discoveries (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  crawl_run_id BINARY(16) NOT NULL,
  video_id BIGINT UNSIGNED NOT NULL,
  source_url VARCHAR(2000) NOT NULL,
  position INT UNSIGNED NULL,
  discovered_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_discovery_run_video (crawl_run_id, video_id),
  CONSTRAINT fk_discovery_run FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id),
  CONSTRAINT fk_discovery_video FOREIGN KEY (video_id) REFERENCES videos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE metric_definitions (
  metric_key VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  namespace VARCHAR(50) NOT NULL,
  description VARCHAR(500) NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (metric_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE raw_artifacts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  crawl_run_id BINARY(16) NOT NULL,
  video_id BIGINT UNSIGNED NULL,
  artifact_type VARCHAR(50) NOT NULL,
  bucket VARCHAR(100) NOT NULL,
  object_key VARCHAR(600) NOT NULL,
  content_type VARCHAR(200) NOT NULL,
  compression VARCHAR(20) NOT NULL,
  etag VARCHAR(200) NULL,
  sha256 CHAR(64) NULL,
  size_bytes BIGINT UNSIGNED NULL,
  storage_status VARCHAR(20) NOT NULL,
  captured_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NULL,
  deleted_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_raw_object (bucket, object_key),
  KEY ix_raw_expiry (storage_status, expires_at),
  CONSTRAINT fk_raw_run FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id),
  CONSTRAINT fk_raw_video FOREIGN KEY (video_id) REFERENCES videos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE metric_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  video_id BIGINT UNSIGNED NOT NULL,
  crawl_run_id BINARY(16) NOT NULL,
  captured_at DATETIME(3) NOT NULL,
  snapshot_hash CHAR(64) NOT NULL,
  raw_artifact_id BIGINT UNSIGNED NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_metric_snapshots_video_time (video_id, captured_at, id),
  CONSTRAINT fk_metric_snapshot_video FOREIGN KEY (video_id) REFERENCES videos(id),
  CONSTRAINT fk_metric_snapshot_run FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id),
  CONSTRAINT fk_metric_snapshot_raw FOREIGN KEY (raw_artifact_id) REFERENCES raw_artifacts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE metric_values (
  snapshot_id BIGINT UNSIGNED NOT NULL,
  metric_key VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  metric_value BIGINT UNSIGNED NULL,
  status VARCHAR(20) NOT NULL,
  source_path VARCHAR(500) NULL,
  extra JSON NOT NULL,
  PRIMARY KEY (snapshot_id, metric_key),
  CONSTRAINT fk_metric_value_snapshot FOREIGN KEY (snapshot_id) REFERENCES metric_snapshots(id),
  CONSTRAINT fk_metric_value_definition FOREIGN KEY (metric_key) REFERENCES metric_definitions(metric_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE comments (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  video_id BIGINT UNSIGNED NOT NULL,
  platform_comment_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  root_platform_comment_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  parent_platform_comment_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  root_comment_id BIGINT UNSIGNED NULL,
  parent_comment_id BIGINT UNSIGNED NULL,
  depth SMALLINT UNSIGNED NOT NULL,
  author_platform_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  author_name VARCHAR(255) NULL,
  content MEDIUMTEXT NOT NULL,
  like_count BIGINT UNSIGNED NULL,
  reply_count BIGINT UNSIGNED NULL,
  published_at DATETIME(3) NULL,
  first_seen_at DATETIME(3) NOT NULL,
  last_seen_at DATETIME(3) NOT NULL,
  status VARCHAR(20) NOT NULL,
  extra JSON NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_comment_platform_id (video_id, platform_comment_id),
  KEY ix_comments_video_time (video_id, published_at, id),
  KEY ix_comments_root (root_comment_id),
  KEY ix_comments_parent (parent_comment_id),
  CONSTRAINT fk_comments_video FOREIGN KEY (video_id) REFERENCES videos(id),
  CONSTRAINT fk_comments_root FOREIGN KEY (root_comment_id) REFERENCES comments(id),
  CONSTRAINT fk_comments_parent FOREIGN KEY (parent_comment_id) REFERENCES comments(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE timed_text_streams (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  video_unit_id BIGINT UNSIGNED NOT NULL,
  content_type VARCHAR(20) NOT NULL,
  stream_key VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  language_code VARCHAR(30) NULL,
  language_code_normalized VARCHAR(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT '',
  source_type VARCHAR(30) NOT NULL,
  captured_at DATETIME(3) NOT NULL,
  raw_artifact_id BIGINT UNSIGNED NULL,
  attributes JSON NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_timed_stream (video_unit_id, content_type, stream_key, language_code_normalized),
  CONSTRAINT fk_timed_stream_unit FOREIGN KEY (video_unit_id) REFERENCES video_units(id),
  CONSTRAINT fk_timed_stream_raw FOREIGN KEY (raw_artifact_id) REFERENCES raw_artifacts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE timed_text_items (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stream_id BIGINT UNSIGNED NOT NULL,
  platform_item_id VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  dedup_key CHAR(64) NOT NULL,
  start_ms BIGINT UNSIGNED NOT NULL,
  end_ms BIGINT UNSIGNED NULL,
  text MEDIUMTEXT NOT NULL,
  published_at DATETIME(3) NULL,
  sender_ref VARCHAR(200) NULL,
  attributes JSON NOT NULL,
  first_seen_at DATETIME(3) NOT NULL,
  last_seen_at DATETIME(3) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_timed_item_dedup (stream_id, dedup_key),
  KEY ix_timed_item_cursor (stream_id, start_ms, id),
  CONSTRAINT fk_timed_item_stream FOREIGN KEY (stream_id) REFERENCES timed_text_streams(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE idempotency_keys (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  idempotency_key VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  request_hash CHAR(64) NOT NULL,
  job_id BINARY(16) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_idempotency_key (idempotency_key),
  KEY ix_idempotency_expiry (expires_at),
  CONSTRAINT fk_idempotency_job FOREIGN KEY (job_id) REFERENCES crawl_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
