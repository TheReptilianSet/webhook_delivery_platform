from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class DeliveryResponse(BaseModel):
    id: str
    event_id: str
    endpoint_id: str
    status: Literal[
        "pending",
        "queued",
        "delivering",
        "retry_scheduled",
        "succeeded",
        "dead_lettered",
        "cancelled",
    ]
    attempt_count: int
    next_attempt_at: datetime | None
    replay_of: str | None
    created_at: datetime


class AttemptResponse(BaseModel):
    id: str
    attempt_number: int
    started_at: datetime
    ended_at: datetime | None
    outcome: Literal["started", "succeeded", "failed", "unknown"]
    response_status: int | None
    latency_ms: int | None
    error_code: str | None
    retry_decision: dict[str, Any] | None
    response_preview_available: bool
    response_preview: str | None = None
    response_preview_encoding: Literal["base64"] | None = None
    response_preview_error: Literal["unavailable"] | None = None
