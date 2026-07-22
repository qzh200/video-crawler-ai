from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from video_crawler.api.errors import ApiError
from video_crawler.api.schemas.jobs import (
    CrawlJobCreateRequest,
    CrawlJobResponse,
    CrawlJobResumeRequest,
)
from video_crawler.application.jobs import JobService, JobServiceError
from video_crawler.domain.errors import DomainValidationError

router = APIRouter(prefix="/crawl-jobs", tags=["crawl-jobs"])


def get_job_service(request: Request) -> JobService:
    service = getattr(request.app.state, "job_service", None)
    if service is None:
        raise ApiError(
            status_code=503,
            code="STORAGE_UNAVAILABLE",
            message="crawl job service is not configured",
        )
    return cast(JobService, service)


def _translate_service_error(error: JobServiceError) -> ApiError:
    return ApiError(
        status_code=error.status_code,
        code=error.code,
        message=error.message,
    )


@router.post("", response_model=CrawlJobResponse, status_code=202)
async def create_job(
    payload: CrawlJobCreateRequest,
    response: Response,
    service: Annotated[JobService, Depends(get_job_service)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> CrawlJobResponse:
    try:
        result = await service.create(
            source_url=str(payload.source_url),
            auth_profile_id=payload.auth_profile_id,
            video_limit=payload.video_limit,
            strategy_overrides=payload.strategy.defined_values(),
            idempotency_key=idempotency_key,
        )
    except JobServiceError as error:
        raise _translate_service_error(error) from error
    except DomainValidationError as error:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message=str(error),
        ) from error
    response.status_code = 202 if result.created else 200
    return CrawlJobResponse.from_record(result.record)


@router.get("/{job_id}", response_model=CrawlJobResponse)
async def get_job(
    job_id: UUID,
    service: Annotated[JobService, Depends(get_job_service)],
) -> CrawlJobResponse:
    try:
        return CrawlJobResponse.from_record(await service.get(job_id))
    except JobServiceError as error:
        raise _translate_service_error(error) from error


@router.post("/{job_id}/cancel", response_model=CrawlJobResponse)
async def cancel_job(
    job_id: UUID,
    service: Annotated[JobService, Depends(get_job_service)],
) -> CrawlJobResponse:
    try:
        return CrawlJobResponse.from_record(await service.cancel(job_id))
    except JobServiceError as error:
        raise _translate_service_error(error) from error


@router.post("/{job_id}/resume", response_model=CrawlJobResponse)
async def resume_job(
    job_id: UUID,
    payload: CrawlJobResumeRequest,
    service: Annotated[JobService, Depends(get_job_service)],
) -> CrawlJobResponse:
    try:
        record = await service.resume(job_id, payload.strategy.defined_values())
    except JobServiceError as error:
        raise _translate_service_error(error) from error
    except DomainValidationError as error:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message=str(error),
        ) from error
    return CrawlJobResponse.from_record(record)
