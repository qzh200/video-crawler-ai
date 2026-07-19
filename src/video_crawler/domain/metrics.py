from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from video_crawler.domain.artifacts import RawArtifactRef
from video_crawler.domain.errors import DomainValidationError


class MetricStatus(StrEnum):
    AVAILABLE = "available"
    UNSUPPORTED = "unsupported"
    NOT_PUBLIC = "not_public"
    FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True, slots=True)
class MetricValue:
    value: int | None
    status: MetricStatus
    source_path: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.value is not None and self.value < 0:
            raise DomainValidationError("value must be nonnegative")
        if self.status is MetricStatus.AVAILABLE and self.value is None:
            raise DomainValidationError("available metric must have a value")
        if self.status is not MetricStatus.AVAILABLE and self.value is not None:
            raise DomainValidationError("metric value must be None unless status is available")


@dataclass(frozen=True, slots=True)
class MetricResult:
    values: Mapping[str, MetricValue]
    raw_artifacts: tuple[RawArtifactRef, ...] = ()
