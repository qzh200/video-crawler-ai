from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Path, Query, Request

from video_crawler.api.errors import ApiError
from video_crawler.api.schemas.results import (
    CommentPageResponse,
    CommentResponse,
    MetricPageResponse,
    MetricSnapshotResponse,
    TimedTextPageResponse,
    TimedTextResponse,
)
from video_crawler.application.cursors import InvalidCursorError
from video_crawler.application.result_queries import ResultQueryService

router = APIRouter(tags=["results"])


def get_result_query_service(request: Request) -> ResultQueryService:
    service = getattr(request.app.state, "result_query_service", None)
    if service is None:
        raise ApiError(
            status_code=503,
            code="STORAGE_UNAVAILABLE",
            message="result query service is not configured",
        )
    return cast(ResultQueryService, service)


def _invalid_cursor(error: InvalidCursorError) -> ApiError:
    return ApiError(status_code=400, code="INVALID_CURSOR", message=str(error))


@router.get("/videos/{video_id}/metrics", response_model=MetricPageResponse)
async def list_metrics(
    video_id: Annotated[int, Path(ge=1)],
    service: Annotated[ResultQueryService, Depends(get_result_query_service)],
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> MetricPageResponse:
    try:
        page = await service.list_metrics(video_id, cursor=cursor, page_size=page_size)
    except InvalidCursorError as error:
        raise _invalid_cursor(error) from error
    return MetricPageResponse(
        items=[MetricSnapshotResponse.from_record(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/videos/{video_id}/metrics/latest", response_model=MetricSnapshotResponse)
async def latest_metric(
    video_id: Annotated[int, Path(ge=1)],
    service: Annotated[ResultQueryService, Depends(get_result_query_service)],
) -> MetricSnapshotResponse:
    record = await service.latest_metric(video_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code="RESULT_NOT_FOUND",
            message="metric snapshot was not found",
        )
    return MetricSnapshotResponse.from_record(record)


@router.get("/videos/{video_id}/comments", response_model=CommentPageResponse)
async def list_comments(
    video_id: Annotated[int, Path(ge=1)],
    service: Annotated[ResultQueryService, Depends(get_result_query_service)],
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 100,
    root_only: bool = False,
    root_comment_id: Annotated[int | None, Query(ge=1)] = None,
    order: Literal["asc", "desc"] = "asc",
) -> CommentPageResponse:
    try:
        page = await service.list_comments(
            video_id,
            cursor=cursor,
            page_size=page_size,
            root_only=root_only,
            root_comment_id=root_comment_id,
            order=order,
        )
    except InvalidCursorError as error:
        raise _invalid_cursor(error) from error
    return CommentPageResponse(
        items=[CommentResponse.from_record(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/video-units/{unit_id}/timed-text", response_model=TimedTextPageResponse)
async def list_timed_text(
    unit_id: Annotated[int, Path(ge=1)],
    service: Annotated[ResultQueryService, Depends(get_result_query_service)],
    content_type: Literal["danmaku", "subtitle"] | None = None,
    language_code: Annotated[str | None, Query(min_length=1, max_length=30)] = None,
    start_ms: Annotated[int | None, Query(ge=0)] = None,
    end_ms: Annotated[int | None, Query(ge=0)] = None,
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> TimedTextPageResponse:
    if start_ms is not None and end_ms is not None and start_ms > end_ms:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="start_ms must not exceed end_ms",
        )
    try:
        page = await service.list_timed_text(
            unit_id,
            cursor=cursor,
            page_size=page_size,
            content_type=content_type,
            language_code=language_code,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InvalidCursorError as error:
        raise _invalid_cursor(error) from error
    return TimedTextPageResponse(
        items=[TimedTextResponse.from_record(item) for item in page.items],
        next_cursor=page.next_cursor,
    )
