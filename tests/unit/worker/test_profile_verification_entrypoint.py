from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from video_crawler.worker import profile_verification_entrypoint

VERIFICATION_ID = UUID("01900000-0000-7000-8000-000000000021")


class FakeContainer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.executed: list[UUID] = []
        self.closed = False

    async def execute_profile_verification(self, verification_id: UUID) -> None:
        self.executed.append(verification_id)
        if self.fail:
            raise RuntimeError("sensitive synthetic failure")

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(("fail", "expected"), [(False, 0), (True, 1)])
def test_entrypoint_maps_execution_to_exit_code_and_closes(
    fail: bool,
    expected: int,
) -> None:
    container = FakeContainer(fail=fail)

    result = asyncio.run(
        profile_verification_entrypoint.run_verification(
            VERIFICATION_ID,
            container_factory=lambda: container,
        )
    )

    assert result == expected
    assert container.executed == [VERIFICATION_ID]
    assert container.closed


def test_cli_parses_verification_id(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[UUID] = []

    async def fake_run(verification_id: UUID) -> int:
        received.append(verification_id)
        return 0

    monkeypatch.setattr(profile_verification_entrypoint, "run_verification", fake_run)

    assert profile_verification_entrypoint.main([str(VERIFICATION_ID)]) == 0
    assert received == [VERIFICATION_ID]
