from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from video_crawler.api.dependencies.auth import require_api_key
from video_crawler.application.cursors import CursorCodec
from video_crawler.application.result_queries import (
    CommentRecord,
    MetricSnapshotRecord,
    MetricValueRecord,
    ResultQueryService,
    TimedTextRecord,
)
from video_crawler.main import create_app

NOW = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)


class InMemoryResultStore:
    def __init__(self) -> None:
        self.comments = [
            CommentRecord(
                id=index,
                platform_comment_id=f"comment-{index}",
                root_comment_id=None,
                parent_comment_id=None,
                depth=0,
                author_platform_id=None,
                author_name=f"author-{index}",
                content=f"content-{index}",
                like_count=index,
                reply_count=0,
                published_at=NOW + timedelta(seconds=index // 2),
                status="available",
                extra={},
            )
            for index in range(1, 8)
        ]
        self.timed_text = [
            TimedTextRecord(
                id=index,
                stream_id=1,
                content_type="danmaku",
                language_code=None,
                start_ms=(index // 2) * 1000,
                end_ms=None,
                text=f"text-{index}",
                published_at=None,
                sender_ref=None,
                attributes={},
            )
            for index in range(1, 8)
        ]
        self.metrics = [
            MetricSnapshotRecord(
                snapshot_id=index,
                captured_at=NOW + timedelta(minutes=index),
                metrics={
                    "standard.views": MetricValueRecord(
                        value=index * 100,
                        status="available",
                    )
                },
            )
            for index in range(1, 4)
        ]

    async def list_metric_snapshots(
        self,
        video_id: int,
        *,
        after: tuple[datetime, int] | None,
        limit: int,
    ) -> list[MetricSnapshotRecord]:
        del video_id
        rows = sorted(
            self.metrics,
            key=lambda item: (item.captured_at, item.snapshot_id),
            reverse=True,
        )
        if after is not None:
            rows = [item for item in rows if (item.captured_at, item.snapshot_id) < after]
        return rows[:limit]

    async def latest_metric_snapshot(self, video_id: int) -> MetricSnapshotRecord | None:
        rows = await self.list_metric_snapshots(video_id, after=None, limit=1)
        return rows[0] if rows else None

    async def list_comments(
        self,
        video_id: int,
        *,
        after: tuple[datetime, int] | None,
        limit: int,
        root_only: bool,
        root_comment_id: int | None,
        order: str,
    ) -> list[CommentRecord]:
        del video_id
        rows = self.comments
        if root_only:
            rows = [item for item in rows if item.depth == 0]
        if root_comment_id is not None:
            rows = [item for item in rows if item.root_comment_id == root_comment_id]
        rows = sorted(
            rows,
            key=lambda item: (item.published_at, item.id),
            reverse=order == "desc",
        )
        if after is not None:
            if order == "asc":
                rows = [item for item in rows if (item.published_at, item.id) > after]
            else:
                rows = [item for item in rows if (item.published_at, item.id) < after]
        return rows[:limit]

    async def list_timed_text(
        self,
        unit_id: int,
        *,
        after: tuple[int, int] | None,
        limit: int,
        content_type: str | None,
        language_code: str | None,
        start_ms: int | None,
        end_ms: int | None,
    ) -> list[TimedTextRecord]:
        del unit_id
        rows = self.timed_text
        if content_type is not None:
            rows = [item for item in rows if item.content_type == content_type]
        if language_code is not None:
            rows = [item for item in rows if item.language_code == language_code]
        if start_ms is not None:
            rows = [item for item in rows if item.start_ms >= start_ms]
        if end_ms is not None:
            rows = [item for item in rows if item.start_ms <= end_ms]
        rows = sorted(rows, key=lambda item: (item.start_ms, item.id))
        if after is not None:
            rows = [item for item in rows if (item.start_ms, item.id) > after]
        return rows[:limit]


def _client() -> TestClient:
    service = ResultQueryService(
        store=InMemoryResultStore(),
        cursor_codec=CursorCodec(b"test-cursor-secret"),
    )
    app = create_app(result_query_service=service)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def _collect_ids(client: TestClient, path: str) -> list[int]:
    ids: list[int] = []
    cursor: str | None = None
    while True:
        params = {"page_size": 3}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(path, params=params)
        assert response.status_code == 200
        body = response.json()
        ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return ids


def test_comment_pages_have_no_duplicates_or_gaps() -> None:
    assert _collect_ids(_client(), "/api/v1/videos/1/comments") == list(range(1, 8))


def test_timed_text_pages_have_no_duplicates_or_gaps() -> None:
    assert _collect_ids(
        _client(),
        "/api/v1/video-units/1/timed-text?content_type=danmaku",
    ) == list(range(1, 8))


def test_metrics_are_descending_and_latest_is_exposed() -> None:
    client = _client()

    page = client.get("/api/v1/videos/1/metrics", params={"page_size": 2})
    latest = client.get("/api/v1/videos/1/metrics/latest")

    assert page.status_code == 200
    assert [item["snapshot_id"] for item in page.json()["items"]] == [3, 2]
    assert page.json()["next_cursor"] is not None
    assert latest.status_code == 200
    assert latest.json()["snapshot_id"] == 3
    assert latest.json()["metrics"]["standard.views"] == {
        "value": 300,
        "status": "available",
    }


def test_page_size_above_contract_maximum_is_structured_validation_error() -> None:
    response = _client().get("/api/v1/videos/1/comments", params={"page_size": 1001})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_tampered_cursor_returns_stable_error() -> None:
    response = _client().get(
        "/api/v1/videos/1/comments",
        params={"cursor": "not-a-valid-cursor"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"
