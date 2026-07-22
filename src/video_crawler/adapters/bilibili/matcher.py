from __future__ import annotations

import re
from urllib.parse import urlsplit

POPULAR_PATH = "/v/popular/all"
_VIDEO_PATH = re.compile(r"/video/(BV[A-Za-z0-9]{10})")


def match_bilibili_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"bilibili.com", "www.bilibili.com"}:
        return False
    path = parsed.path.rstrip("/") or "/"
    return path == POPULAR_PATH or _VIDEO_PATH.fullmatch(path) is not None


def extract_bvid(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"bilibili.com", "www.bilibili.com"}:
        return None
    matched = _VIDEO_PATH.fullmatch(parsed.path.rstrip("/"))
    return matched.group(1) if matched is not None else None
