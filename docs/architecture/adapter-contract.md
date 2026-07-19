# Adapter Contract

## 1. 目的

Adapter 将平台 URL、协议和响应转换成通用领域模型。Worker 和 Core 只能依赖本契约，不得调用站点私有函数。

## 2. 建议接口

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class VideoSiteAdapter(Protocol):
    platform_key: str

    def match(self, url: str) -> bool: ...

    async def verify_auth(
        self,
        context: AdapterContext,
    ) -> AuthVerificationResult: ...

    async def resolve_target(
        self,
        context: AdapterContext,
        url: str,
    ) -> ResolvedTarget: ...

    async def discover_targets(
        self,
        context: AdapterContext,
        target: ResolvedTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[DiscoveredTarget]: ...

    async def fetch_metrics(
        self,
        context: AdapterContext,
        target: VideoTarget,
    ) -> MetricResult: ...

    async def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]: ...

    async def fetch_timed_text(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[TimedTextBatch]: ...
```

## 3. AdapterContext

Core 注入以下 Gateway：

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdapterContext:
    browser: BrowserGateway
    http: HttpGateway
    network_capture: NetworkCaptureGateway
    raw_artifacts: RawArtifactGateway
    rate_limiter: RateLimiter
    cancellation: CancellationToken
    logger: BoundLogger
    auth_profile: AuthProfileContext
```

Adapter 不得持有 SQLAlchemy Session、MinIO Client 或直接的 Crawl4AI 实例。

## 4. 目标模型

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TargetKind(StrEnum):
    SINGLE_VIDEO = "single_video"
    VIDEO_LIST = "video_list"


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    platform: str
    kind: TargetKind
    canonical_url: str
    platform_video_id: str | None = None
    platform_ids: dict[str, str | int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    platform: str
    platform_video_id: str
    canonical_url: str
    position: int | None
    platform_ids: dict[str, str | int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VideoTarget:
    platform: str
    platform_video_id: str
    canonical_url: str
    platform_ids: dict[str, str | int]
```

## 5. 指标模型

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricResult:
    values: dict[str, MetricValue]
    raw_artifacts: tuple[RawArtifactRef, ...] = ()
```

Adapter 必须使用命名空间键。标准键由 Core 注册，站点键由 Adapter 注册。

## 6. 评论模型

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedComment:
    platform_comment_id: str
    root_platform_comment_id: str | None
    parent_platform_comment_id: str | None
    author_platform_id: str | None
    author_name: str | None
    content: str
    like_count: int | None
    reply_count: int | None
    published_at: datetime | None
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommentBatch:
    items: tuple[NormalizedComment, ...]
    cursor: str | None
    has_more: bool
    raw_artifacts: tuple[RawArtifactRef, ...] = ()
```

## 7. 时间文本模型

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TimedTextType(StrEnum):
    DANMAKU = "danmaku"
    SUBTITLE = "subtitle"


@dataclass(frozen=True, slots=True)
class TimedTextStreamDescriptor:
    platform_unit_id: str
    content_type: TimedTextType
    stream_key: str
    language_code: str | None
    source_type: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedTimedText:
    platform_item_id: str | None
    start_ms: int
    end_ms: int | None
    text: str
    published_at: datetime | None
    sender_ref: str | None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TimedTextBatch:
    stream: TimedTextStreamDescriptor
    items: tuple[NormalizedTimedText, ...]
    raw_artifacts: tuple[RawArtifactRef, ...] = ()
```

## 8. Gateway 规则

- `BrowserGateway`：统一创建页面、执行 JavaScript、等待选择器、捕获响应；
- `HttpGateway`：统一携带浏览器会话信息、限速、超时和重试；
- `RawArtifactGateway`：Adapter 只提交 bytes/metadata，Core 决定对象路径和 MinIO 写入；
- `CancellationToken`：所有分页和批次边界必须检查；
- `BoundLogger`：必须自动附带 job/run/video/module 信息并脱敏。

## 9. Bilibili Adapter 目录

```text
src/video_crawler/adapters/bilibili/
├── __init__.py
├── adapter.py
├── matcher.py
├── auth.py
├── resolver.py
├── discovery.py
├── metrics.py
├── comments.py
├── timed_text.py
├── parsers/
└── fixtures/  # 仅测试使用，必须脱敏
```

Bilibili 内部 ID 只存在于该目录和 `platform_ids`/`extra` JSON 中。
