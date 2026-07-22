from fastapi import APIRouter, Depends

from video_crawler.api.dependencies.auth import require_api_key
from video_crawler.api.routes import auth_profiles, jobs

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
api_router.include_router(jobs.router)
api_router.include_router(auth_profiles.router)
