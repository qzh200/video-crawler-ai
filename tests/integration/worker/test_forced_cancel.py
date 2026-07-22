from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups"),
]


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_forced_cancel_terminates_child_and_grandchild() -> None:
    from video_crawler.infrastructure.process.groups import terminate_process_group

    helper = (
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(child.pid, flush=True); "
        "time.sleep(60)"
    )
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and synthetic helper
        [sys.executable, "-c", helper],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    grandchild_pid = int(process.stdout.readline().strip())
    process_group_id = os.getpgid(process.pid)

    try:
        terminate_process_group(
            process_group_id,
            grace_seconds=0.2,
            kill_timeout_seconds=2.0,
        )
        process.wait(timeout=2.0)
        deadline = time.monotonic() + 2.0
        while _pid_exists(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.01)

        assert not _pid_exists(process.pid)
        assert not _pid_exists(grandchild_pid)
    finally:
        if process.poll() is None:
            os.killpg(process_group_id, 9)
            process.wait(timeout=2.0)
