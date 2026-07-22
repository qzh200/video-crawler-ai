from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_crawler.cli import build_parser, main, run_login
from video_crawler.core.config import Settings

PROJECT_ROOT = Path(__file__).parents[2]


class FakePage:
    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.page = FakePage()
        self.opened: tuple[str, float, bool] | None = None
        self.closed = False

    async def open_page(
        self,
        url: str,
        *,
        timeout_seconds: float,
        capture_network: bool = False,
    ) -> FakePage:
        self.opened = (url, timeout_seconds, capture_network)
        return self.page

    async def close(self) -> None:
        self.closed = True


def make_settings(profile_root: Path) -> Settings:
    return Settings(
        api_key="test-api-key",
        mysql_password="test-mysql-password",  # noqa: S106
        minio_secret_key="test-minio-secret",  # noqa: S106
        browser_profile_root=profile_root,
    )


@pytest.mark.parametrize("profile", ["../escape", "a/b", "a\\b", "", ".", ".."])
def test_login_parser_rejects_unsafe_profile_names(profile: str) -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["login", "--platform", "bilibili", "--profile", profile])

    assert error.value.code == 2


def test_login_parser_rejects_unknown_platform() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["login", "--platform", "unknown", "--profile", "profile-1"])

    assert error.value.code == 2


@pytest.mark.asyncio
async def test_login_uses_worker_profile_root_and_visible_browser(tmp_path: Path) -> None:
    browser = FakeBrowser()
    factory_values: dict[str, Any] = {}
    prompts: list[str] = []
    output: list[str] = []

    def browser_factory(**values: Any) -> FakeBrowser:
        factory_values.update(values)
        return browser

    exit_code = await run_login(
        platform="bilibili",
        profile_directory="bilibili-main",
        settings=make_settings(tmp_path),
        browser_factory=browser_factory,
        wait_for_user=lambda prompt: prompts.append(prompt) or "",
        output=output.append,
    )

    assert exit_code == 0
    assert factory_values == {
        "profile_root": tmp_path,
        "profile_directory": "bilibili-main",
        "headless": False,
        "text_mode": False,
    }
    assert browser.opened == ("https://www.bilibili.com/", 60, False)
    assert browser.closed is True
    assert len(prompts) == 1
    assert any("bilibili-main" in line for line in output)


def test_main_dispatches_login_without_starting_worker(tmp_path: Path) -> None:
    calls: list[tuple[str, str, Path]] = []

    async def login_runner(
        *,
        platform: str,
        profile_directory: str,
        settings: Settings,
    ) -> int:
        calls.append((platform, profile_directory, settings.browser_profile_root))
        return 0

    exit_code = main(
        ["login", "--platform", "bilibili", "--profile", "bilibili-main"],
        settings=make_settings(tmp_path),
        login_runner=login_runner,
    )

    assert exit_code == 0
    assert calls == [("bilibili", "bilibili-main", tmp_path)]


def test_docker_build_retries_and_caches_slow_dependency_downloads() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "PIP_DEFAULT_TIMEOUT=120" in dockerfile
    assert "PIP_RETRIES=10" in dockerfile
    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "--no-cache-dir" not in dockerfile
