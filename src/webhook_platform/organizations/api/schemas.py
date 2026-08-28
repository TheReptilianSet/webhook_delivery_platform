from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class MemberCreateRequest(BaseModel):
    email: EmailStr
    role: Literal["owner", "admin", "member"]


class MemberUpdateRequest(BaseModel):
    role: Literal["owner", "admin", "member"]


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Literal["events:write"]] = Field(min_length=1, max_length=1)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    status: Literal["active", "disabled"]
    role: Literal["owner", "admin", "member"]


class MemberResponse(BaseModel):
    user_id: str
    email: EmailStr | None = None
    role: Literal["owner", "admin", "member"]


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[Literal["events:write"]]
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str
