from __future__ import annotations

import subprocess
import sys
from typing import Any
from uuid import UUID

from video_crawler.infrastructure.process.groups import (
    spawn_profile_verification_process,
    spawn_task_process,
)

RUN_ID = UUID("01900000-0000-7000-8000-000000000002")


class DummyPopen:
    pid = 9876
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def test_spawn_task_process_uses_an_isolated_session_without_shell(
    monkeypatch: Any,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> DummyPopen:
        captured["command"] = command
        captured.update(kwargs)
        return DummyPopen()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = spawn_task_process(RUN_ID)

    assert captured == {
        "command": [
            sys.executable,
            "-m",
            "video_crawler.worker.task_entrypoint",
            str(RUN_ID),
        ],
        "shell": False,
        "start_new_session": True,
    }
    assert process.pid == 9876
    assert process.process_group_id == 9876


def test_spawn_profile_verification_uses_fixed_isolated_entrypoint(
    monkeypatch: Any,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> DummyPopen:
        captured["command"] = command
        captured.update(kwargs)
        return DummyPopen()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = spawn_profile_verification_process(RUN_ID)

    assert captured == {
        "command": [
            sys.executable,
            "-m",
            "video_crawler.worker.profile_verification_entrypoint",
            str(RUN_ID),
        ],
        "shell": False,
        "start_new_session": True,
    }
    assert process.process_group_id == 9876
