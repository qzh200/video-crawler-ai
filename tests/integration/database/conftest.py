from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.mysql import MySqlContainer

from video_crawler.core.config import get_settings
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


@pytest.fixture(scope="module")
def mysql_url() -> Iterator[str]:
    with MySqlContainer("mysql:8.4", dialect="pymysql") as mysql:
        host = mysql.get_container_host_ip()
        if host == "localhost":
            host = "127.0.0.1"
        environment = {
            "API_KEY": "test-api-key",
            "MYSQL_HOST": host,
            "MYSQL_PORT": str(mysql.get_exposed_port(mysql.port)),
            "MYSQL_DATABASE": mysql.dbname,
            "MYSQL_USER": mysql.username,
            "MYSQL_PASSWORD": mysql.password,
            "MINIO_SECRET_KEY": "test-minio-secret",
        }
        with patch.dict(os.environ, environment):
            get_settings.cache_clear()
            command.upgrade(Config("alembic.ini"), "head")
            yield (
                mysql.get_connection_url()
                .replace("mysql+pymysql", "mysql+asyncmy")
                .replace("localhost", host)
            )
            get_settings.cache_clear()


@pytest.fixture
async def database(mysql_url: str) -> AsyncIterator[DatabaseSessionFactory]:
    engine: AsyncEngine = create_async_engine(mysql_url, pool_pre_ping=True)
    factory = DatabaseSessionFactory(engine=engine)
    try:
        yield factory
    finally:
        await factory.dispose()
