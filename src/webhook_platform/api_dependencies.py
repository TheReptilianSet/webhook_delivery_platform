from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.config.settings import Settings
from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.infrastructure.models import ApiKeyModel, UserModel
from webhook_platform.shared.infrastructure.security import (
    api_key_digest,
    decode_access_token,
    parse_api_key,
)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.container.sessions() as session:
        yield session


def settings_from(request: Request) -> Settings:
    return cast("Settings", request.app.state.container.settings)


async def current_user_id(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AppError("authentication_required", "Authentication required", status_code=401)
    token = authorization[7:]
    try:
        user_id = decode_access_token(settings_from(request), token)
    except jwt.PyJWTError as exc:
        raise AppError("invalid_token", "Authentication required", status_code=401) from exc
    user = await session.get(UserModel, user_id)
    if user is None or not user.active:
        raise AppError("invalid_token", "Authentication required", status_code=401)
    settings = settings_from(request)
    await request.app.state.container.rate_limiter.require(
        f"management:{user_id}",
        rate=settings.management_rate_per_second,
        capacity=settings.management_rate_burst,
    )
    return user_id


@dataclass(frozen=True)
class ProducerPrincipal:
    organization_id: str
    api_key_id: str


async def producer_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ProducerPrincipal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AppError("authentication_required", "Authentication required", status_code=401)
    plaintext = authorization[7:]
    settings = settings_from(request)
    if plaintext.startswith("whk_test_") and not settings.accept_test_api_keys:
        raise AppError("invalid_api_key", "API key is invalid", status_code=401)
    parsed = parse_api_key(plaintext)
    if parsed is None:
        raise AppError("invalid_api_key", "API key is invalid", status_code=401)
    prefix, secret = parsed
    key = await session.scalar(select(ApiKeyModel).where(ApiKeyModel.prefix == prefix))
    if (
        key is None
        or key.revoked_at is not None
        or "events:write" not in key.scopes
        or not hmac.compare_digest(key.secret_digest, api_key_digest(settings, secret))
    ):
        raise AppError("invalid_api_key", "API key is invalid", status_code=401)
    key.last_used_at = datetime.now(UTC)
    await session.commit()
    await request.app.state.container.rate_limiter.require(
        f"producer:{key.organization_id}",
        rate=settings.producer_rate_per_second,
        capacity=settings.producer_rate_burst,
    )
    return ProducerPrincipal(key.organization_id, key.id)
