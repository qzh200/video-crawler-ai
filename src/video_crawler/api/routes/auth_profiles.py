from __future__ import annotations

from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from video_crawler.api.errors import ApiError
from video_crawler.api.schemas.auth_profiles import (
    AuthProfileCreateRequest,
    AuthProfileResponse,
    AuthProfileVerificationResponse,
)

router = APIRouter(prefix="/auth-profiles", tags=["auth-profiles"])


class AuthProfileOperations(Protocol):
    async def create(self, request: AuthProfileCreateRequest) -> AuthProfileResponse: ...

    async def list(self) -> tuple[AuthProfileResponse, ...]: ...

    async def get(self, profile_id: UUID) -> AuthProfileResponse | None: ...

    async def request_verification(
        self, profile_id: UUID
    ) -> AuthProfileVerificationResponse | None: ...

    async def get_verification(
        self,
        profile_id: UUID,
        verification_id: UUID,
    ) -> AuthProfileVerificationResponse | None: ...

    async def enable(self, profile_id: UUID) -> AuthProfileResponse | None: ...

    async def disable(self, profile_id: UUID) -> AuthProfileResponse | None: ...


def get_profile_service(request: Request) -> AuthProfileOperations:
    service = getattr(request.app.state, "profile_service", None)
    if service is None:
        raise ApiError(
            status_code=503,
            code="STORAGE_UNAVAILABLE",
            message="auth Profile service is not configured",
        )
    return cast(AuthProfileOperations, service)


def _require_profile(profile: AuthProfileResponse | None) -> AuthProfileResponse:
    if profile is None:
        raise ApiError(
            status_code=404,
            code="PROFILE_NOT_FOUND",
            message="auth Profile was not found",
        )
    return profile


@router.post("", response_model=AuthProfileResponse, status_code=201)
async def create_profile(
    payload: AuthProfileCreateRequest,
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> AuthProfileResponse:
    return await service.create(payload)


@router.get("", response_model=list[AuthProfileResponse])
async def list_profiles(
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> tuple[AuthProfileResponse, ...]:
    return await service.list()


@router.get("/{profile_id}", response_model=AuthProfileResponse)
async def get_profile(
    profile_id: UUID,
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> AuthProfileResponse:
    return _require_profile(await service.get(profile_id))


@router.post(
    "/{profile_id}/verify",
    response_model=AuthProfileVerificationResponse,
    status_code=202,
)
async def verify_profile(
    profile_id: UUID,
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> AuthProfileVerificationResponse:
    verification = await service.request_verification(profile_id)
    if verification is None:
        raise ApiError(
            status_code=404,
            code="PROFILE_NOT_FOUND",
            message="auth Profile was not found",
        )
    return verification


@router.get(
    "/{profile_id}/verifications/{verification_id}",
    response_model=AuthProfileVerificationResponse,
)
async def get_profile_verification(
    profile_id: UUID,
    verification_id: UUID,
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> AuthProfileVerificationResponse:
    verification = await service.get_verification(profile_id, verification_id)
    if verification is None:
        raise ApiError(
            status_code=404,
            code="PROFILE_VERIFICATION_NOT_FOUND",
            message="Profile verification request was not found",
        )
    return verification


@router.post("/{profile_id}/enable", response_model=AuthProfileResponse)
async def enable_profile(
    profile_id: UUID,
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> AuthProfileResponse:
    return _require_profile(await service.enable(profile_id))


@router.post("/{profile_id}/disable", response_model=AuthProfileResponse)
async def disable_profile(
    profile_id: UUID,
    service: Annotated[AuthProfileOperations, Depends(get_profile_service)],
) -> AuthProfileResponse:
    return _require_profile(await service.disable(profile_id))
