from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from testcontainers.mysql import MySqlContainer

from video_crawler.core.config import get_settings

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "alembic_version",
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

EXPECTED_METRIC_KEYS = {
    "standard.views",
    "standard.likes",
    "standard.favorites",
    "standard.shares",
    "standard.comments",
    "standard.timed_comments",
    "bilibili.coins",
}


@contextmanager
def configured_database(mysql: MySqlContainer) -> Iterator[Engine]:
    container_host = mysql.get_container_host_ip()
    if container_host == "localhost":
        container_host = "127.0.0.1"
    environment = {
        "API_KEY": "test-api-key",
        "MYSQL_HOST": container_host,
        "MYSQL_PORT": str(mysql.get_exposed_port(mysql.port)),
        "MYSQL_DATABASE": mysql.dbname,
        "MYSQL_USER": mysql.username,
        "MYSQL_PASSWORD": mysql.password,
        "MINIO_SECRET_KEY": "test-minio-secret",
    }
    with patch.dict(os.environ, environment):
        get_settings.cache_clear()
        engine = create_engine(mysql.get_connection_url())
        try:
            yield engine
        finally:
            engine.dispose()
            get_settings.cache_clear()


def test_empty_database_upgrades_seeds_and_downgrades() -> None:
    with MySqlContainer("mysql:8.4", dialect="pymysql") as mysql:
        with configured_database(mysql) as engine:
            alembic_config = Config("alembic.ini")

            command.upgrade(alembic_config, "head")

            assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
            with engine.connect() as connection:
                metric_keys = set(
                    connection.execute(text("SELECT metric_key FROM metric_definitions")).scalars()
                )
            assert metric_keys == EXPECTED_METRIC_KEYS
            command.check(alembic_config)

            command.downgrade(alembic_config, "base")

            assert set(inspect(engine).get_table_names()) == {"alembic_version"}
