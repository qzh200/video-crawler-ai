from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from video_crawler.infrastructure.database.models import (
    AuthProfile,
    AuthProfileVerification,
    Platform,
)
from video_crawler.infrastructure.database.repositories.profile_verifications import (
    ProfileVerificationRepository,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def clear_profile_verification_requests(
    database: DatabaseSessionFactory,
) -> None:
    async with database.transaction() as session:
        await session.execute(delete(AuthProfileVerification))


async def _insert_profile(
    database: DatabaseSessionFactory,
    *,
    status: str = "active",
) -> UUID:
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
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
    return profile_id


@pytest.mark.asyncio
async def test_request_marks_profile_expired_and_reuses_live_request(
    database: DatabaseSessionFactory,
) -> None:
    profile_id = await _insert_profile(database)
    repository = ProfileVerificationRepository(database)
    now = datetime.now(UTC)

    first = await repository.request(profile_id, now)
    second = await repository.request(profile_id, now + timedelta(seconds=1))

    assert first is not None
    assert second is not None
    assert second.verification_id == first.verification_id
    assert first.status == "pending"
    assert first.profile_status == "expired"
    async with database() as session:
        profile = await session.get(AuthProfile, profile_id)
    assert profile is not None and profile.status == "expired"


@pytest.mark.asyncio
async def test_terminal_request_allows_a_new_request(
    database: DatabaseSessionFactory,
) -> None:
    profile_id = await _insert_profile(database)
    repository = ProfileVerificationRepository(database)
    now = datetime.now(UTC)
    first = await repository.request(profile_id, now)
    assert first is not None
    claimed = await repository.claim_next(
        "worker-1",
        now,
        stale_before=now - timedelta(seconds=30),
    )
    assert claimed is not None and claimed.verification_id == first.verification_id

    assert await repository.mark_failed(
        first.verification_id,
        "PROFILE_VERIFICATION_FAILED",
        "Profile verification failed",
        now + timedelta(seconds=1),
    )
    second = await repository.request(profile_id, now + timedelta(seconds=2))

    assert second is not None
    assert second.verification_id != first.verification_id
    assert second.status == "pending"


@pytest.mark.asyncio
async def test_claim_returns_generic_profile_context(
    database: DatabaseSessionFactory,
) -> None:
    profile_id = await _insert_profile(database)
    repository = ProfileVerificationRepository(database)
    now = datetime.now(UTC)
    request = await repository.request(profile_id, now)
    assert request is not None

    claimed = await repository.claim_next(
        "worker-1",
        now,
        stale_before=now - timedelta(seconds=30),
    )

    assert claimed is not None
    assert claimed.verification_id == request.verification_id
    assert claimed.profile_id == profile_id
    assert claimed.platform.startswith("test-")
    assert claimed.profile_directory.startswith("profile-")
    stored = await repository.get(profile_id, request.verification_id)
    assert stored is not None
    assert stored.status == "running"
    assert stored.worker_id == "worker-1"


@pytest.mark.asyncio
async def test_claim_reclaims_only_stale_running_request(
    database: DatabaseSessionFactory,
) -> None:
    profile_id = await _insert_profile(database)
    repository = ProfileVerificationRepository(database)
    now = datetime.now(UTC)
    request = await repository.request(profile_id, now)
    assert request is not None
    first = await repository.claim_next(
        "worker-old",
        now,
        stale_before=now - timedelta(seconds=30),
    )
    assert first is not None

    fresh = await repository.claim_next(
        "worker-new",
        now + timedelta(seconds=10),
        stale_before=now - timedelta(seconds=20),
    )
    stale = await repository.claim_next(
        "worker-new",
        now + timedelta(seconds=31),
        stale_before=now + timedelta(seconds=1),
    )

    assert fresh is None
    assert stale is not None
    assert stale.verification_id == request.verification_id
    assert stale.worker_id == "worker-new"
