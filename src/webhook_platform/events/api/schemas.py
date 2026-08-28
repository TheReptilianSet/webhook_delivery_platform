from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventCreateRequest(BaseModel):
    type: str = Field(min_length=3, max_length=128)
    version: int = Field(ge=1, le=32767)
    occurred_at: datetime
    data: dict[str, Any]


class EventAcceptedResponse(BaseModel):
    event_id: str
    status: Literal["accepted"]
    delivery_count: int
    created_at: datetime


class EventResponse(BaseModel):
    id: str
    type: str
    version: int
    occurred_at: datetime
    data: dict[str, Any]
    created_at: datetime


class EventDetailResponse(EventResponse):
    delivery_summary: dict[str, int]
