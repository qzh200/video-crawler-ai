from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from video_crawler.infrastructure.browser.profiles import validate_profile_directory


class AuthProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    profile_name: str = Field(min_length=1, max_length=100)
    profile_directory: str

    @field_validator("profile_directory")
    @classmethod
    def validate_directory(cls, value: str) -> str:
        return validate_profile_directory(value)


class AuthProfileResponse(BaseModel):
    profile_id: UUID
    platform: str
    profile_name: str
    profile_directory: str
    status: Literal["active", "expired", "disabled"]
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuthProfileVerificationResponse(BaseModel):
    verification_id: UUID
    profile_id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    profile_status: Literal["active", "expired", "disabled"]
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
