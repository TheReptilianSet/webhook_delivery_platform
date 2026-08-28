from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class LogoutRequest(RefreshRequest):
    pass


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    active: bool
    created_at: datetime


class RegistrationResponse(BaseModel):
    user: UserResponse
    organization: dict[str, str]
    membership: dict[str, Literal["owner", "admin", "member"]]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    access_expires_at: datetime
    refresh_expires_at: datetime


class MembershipResponse(BaseModel):
    organization_id: str
    role: Literal["owner", "admin", "member"]


class MeResponse(BaseModel):
    user: UserResponse
    memberships: list[MembershipResponse]
