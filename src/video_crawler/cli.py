from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any, Protocol

from video_crawler.core.config import Settings, get_settings
from video_crawler.infrastructure.browser.crawl4ai_gateway import (
    Crawl4AIBrowserGateway,
)
from video_crawler.infrastructure.browser.profiles import (
    resolve_profile_path,
    validate_profile_directory,
)

_LOGIN_URLS = {"bilibili": "https://www.bilibili.com/"}


class LoginBrowser(Protocol):
    async def open_page(
        self,
        url: str,
        *,
        timeout_seconds: float,
        capture_network: bool = False,
    ) -> object: ...

    async def close(self) -> None: ...


type BrowserFactory = Callable[..., LoginBrowser]
type LoginRunner = Callable[..., Coroutine[Any, Any, int]]
type WaitForUser = Callable[[str], str]
type Output = Callable[[str], None]


def _profile_directory(value: str) -> str:
    try:
        return validate_profile_directory(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Video crawler operations")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="open an interactive platform login")
    login.add_argument("--platform", required=True, choices=tuple(_LOGIN_URLS))
    login.add_argument("--profile", required=True, type=_profile_directory)
    return parser


async def run_login(
    *,
    platform: str,
    profile_directory: str,
    settings: Settings,
    browser_factory: BrowserFactory = Crawl4AIBrowserGateway,
    wait_for_user: WaitForUser = input,
    output: Output = print,
) -> int:
    """Open a visible persistent browser without starting the Worker."""

    try:
        login_url = _LOGIN_URLS[platform]
    except KeyError as exc:
        raise ValueError(f"unsupported platform: {platform}") from exc

    profile_path: Path = resolve_profile_path(
        settings.browser_profile_root,
        profile_directory,
    )
    await asyncio.to_thread(profile_path.mkdir, parents=True, exist_ok=True)
    browser = browser_factory(
        profile_root=settings.browser_profile_root,
        profile_directory=profile_directory,
        headless=False,
        text_mode=False,
    )
    output(f"Opening {platform} login with Profile '{profile_directory}'.")
    output(f"Profile data directory: {profile_path}")
    try:
        await browser.open_page(
            login_url,
            timeout_seconds=settings.default_page_timeout_seconds,
            capture_network=False,
        )
        wait_for_user("Complete login in the browser, then press Enter to save and close: ")
    finally:
        await browser.close()
    output("Browser closed. Verify the Profile through the API before creating a crawl job.")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    login_runner: LoginRunner = run_login,
) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "login":
        return asyncio.run(
            login_runner(
                platform=arguments.platform,
                profile_directory=arguments.profile,
                settings=settings or get_settings(),
            )
        )
    raise RuntimeError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
