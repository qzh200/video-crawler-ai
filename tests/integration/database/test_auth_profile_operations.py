from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from video_crawler.api.schemas.auth_profiles import AuthProfileCreateRequest
from video_crawler.bootstrap import _AuthProfileOperations
from video_crawler.infrastructure.database.models import AuthProfile, Platform
from video_crawler.infrastructure.database.repositories.profile_verifications import (
    ProfileVerificationRepository,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory

pytestmark = pytest.mark.integration


class AllowingAdapterRegistry:
    def get(self, platform: str) -> object:
        assert platform.startswith("test-")
        return object()


@pytest.mark.asyncio
async def test_operations_create_profile_as_expired_until_worker_verifies(
    database: DatabaseSessionFactory,
) -> None:
    platform = f"test-{uuid4().hex[:12]}"
    dependencies = SimpleNamespace(
        sessions=database,
        adapter_registry=AllowingAdapterRegistry(),
        profile_verifications=ProfileVerificationRepository(database),
    )
    operations = _AuthProfileOperations(cast(Any, dependencies))

    created = await operations.create(
        AuthProfileCreateRequest(
            platform=platform,
            profile_name="main",
            profile_directory=f"profile-{uuid4().hex[:12]}",
        )
    )

    assert created.status == "expired"
    assert created.last_verified_at is None


@pytest.mark.asyncio
async def test_operations_queue_and_reuse_verification_without_browser_dependency(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    profile_id = uuid4()
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"test-{uuid4().hex[:12]}",
            display_name="Test",
            adapter_version="1",
            created_at=now,
        )
        session.add(platform)
        await session.flush()
        session.add(
            AuthProfile(
                id=profile_id,
                platform_id=platform.id,
                profile_name="main",
                profile_directory=f"profile-{uuid4().hex[:12]}",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    dependencies = SimpleNamespace(
        sessions=database,
        profile_verifications=ProfileVerificationRepository(database),
    )
    operations = _AuthProfileOperations(cast(Any, dependencies))

    first = await operations.request_verification(profile_id)
    second = await operations.request_verification(profile_id)

    assert first is not None
    assert second is not None
    assert first.verification_id == second.verification_id
    assert first.status == "pending"
    assert first.profile_status == "expired"
    fetched = await operations.get_verification(profile_id, first.verification_id)
    assert fetched == first
