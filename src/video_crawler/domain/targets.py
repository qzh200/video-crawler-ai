from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from video_crawler.domain.errors import DomainValidationError

type PlatformIdValue = str | int


class TargetKind(StrEnum):
    SINGLE_VIDEO = "single_video"
    VIDEO_LIST = "video_list"


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    platform: str
    kind: TargetKind
    canonical_url: str
    platform_video_id: str | None = None
    platform_ids: Mapping[str, PlatformIdValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    platform: str
    platform_video_id: str
    canonical_url: str
    position: int | None
    platform_ids: Mapping[str, PlatformIdValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.position is not None and self.position < 0:
            raise DomainValidationError("position must be nonnegative")


@dataclass(frozen=True, slots=True)
class VideoTarget:
    platform: str
    platform_video_id: str
    canonical_url: str
    platform_ids: Mapping[str, PlatformIdValue]
