from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from video_crawler.api.errors import ApiError, error_payload
from video_crawler.api.router import api_router


async def _api_error_handler(request: Request, error: Exception) -> JSONResponse:
    del request
    assert isinstance(error, ApiError)
    return JSONResponse(
        status_code=error.status_code,
        content=error_payload(error.code, error.message, details=error.details),
    )


async def _validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    del request
    assert isinstance(error, RequestValidationError)
    details = {
        "errors": [
            {
                "type": item.get("type"),
                "location": list(item.get("loc", ())),
                "message": item.get("msg"),
            }
            for item in error.errors()
        ]
    }
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "VALIDATION_ERROR",
            "request validation failed",
            details=details,
        ),
    )


async def _http_error_handler(request: Request, error: Exception) -> JSONResponse:
    del request
    assert isinstance(error, HTTPException)
    if isinstance(error.detail, dict) and "error" in error.detail:
        content = error.detail
    else:
        content = error_payload("HTTP_ERROR", str(error.detail))
    return JSONResponse(status_code=error.status_code, content=content, headers=error.headers)


def create_app(
    *,
    job_service: Any | None = None,
    profile_service: Any | None = None,
) -> FastAPI:
    application = FastAPI(title="Video Crawler API", version="0.1.0")
    application.state.job_service = job_service
    application.state.profile_service = profile_service
    application.add_exception_handler(ApiError, _api_error_handler)
    application.add_exception_handler(RequestValidationError, _validation_error_handler)
    application.add_exception_handler(HTTPException, _http_error_handler)
    application.include_router(api_router)
    return application


app = create_app()
