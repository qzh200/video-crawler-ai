from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from video_crawler.application.health import ComponentHealth, HealthService

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ComponentHealthResponse(BaseModel):
    status: str
    current_revision: str | None = None
    expected_revision: str | None = None
    name: str | None = None

    @classmethod
    def from_component(cls, component: ComponentHealth) -> ComponentHealthResponse:
        return cls(
            status=component.status,
            current_revision=component.current_revision,
            expected_revision=component.expected_revision,
            name=component.name,
        )


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    components: dict[str, ComponentHealthResponse]


def get_health_service(request: Request) -> HealthService | None:
    service = getattr(request.app.state, "health_service", None)
    return cast(HealthService | None, service)


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
)
async def ready(
    response: Response,
    service: Annotated[HealthService | None, Depends(get_health_service)],
) -> ReadinessResponse:
    if service is None:
        response.status_code = 503
        return ReadinessResponse(
            status="not_ready",
            components={"service": ComponentHealthResponse(status="unconfigured")},
        )

    report = await service.check_readiness()
    if not report.ready:
        response.status_code = 503
    return ReadinessResponse(
        status="ready" if report.ready else "not_ready",
        components={
            name: ComponentHealthResponse.from_component(component)
            for name, component in report.components.items()
        },
    )
