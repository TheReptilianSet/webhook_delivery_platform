from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EndpointCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    event_types: list[str] = Field(min_length=1, max_length=50)


class EndpointUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    event_types: list[str] | None = Field(default=None, min_length=1, max_length=50)
    enabled: bool | None = None


class EndpointResponse(BaseModel):
    id: str
    name: str
    url: str
    status: Literal["pending_verification", "active", "disabled", "deleted"]
    enabled: bool
    event_types: list[str]
    created_at: datetime


class EndpointCreatedResponse(EndpointResponse):
    signing_secret: str
