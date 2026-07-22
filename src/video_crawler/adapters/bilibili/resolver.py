from __future__ import annotations

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili.matcher import POPULAR_PATH, extract_bvid
from video_crawler.domain.targets import ResolvedTarget, TargetKind

PLATFORM_KEY = "bilibili"
POPULAR_URL = f"https://www.bilibili.com{POPULAR_PATH}"


async def resolve_bilibili_target(context: AdapterContext, url: str) -> ResolvedTarget:
    del context
    bvid = extract_bvid(url)
    if bvid is not None:
        return ResolvedTarget(
            platform=PLATFORM_KEY,
            kind=TargetKind.SINGLE_VIDEO,
            canonical_url=canonical_video_url(bvid),
            platform_video_id=bvid,
            platform_ids={"bvid": bvid},
        )
    if _is_popular_url(url):
        return ResolvedTarget(
            platform=PLATFORM_KEY,
            kind=TargetKind.VIDEO_LIST,
            canonical_url=POPULAR_URL,
        )
    raise ValueError("unsupported Bilibili target URL")


def canonical_video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"


def _is_popular_url(url: str) -> bool:
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"bilibili.com", "www.bilibili.com"}
        and parsed.path.rstrip("/") == POPULAR_PATH
    )
