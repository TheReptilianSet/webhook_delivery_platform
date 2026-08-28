from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from webhook_platform.config.settings import Settings
from webhook_platform.identity.application.ports import IdentityRepository, UnitOfWork
from webhook_platform.identity.application.security import IdentitySecurity
from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.domain.ids import new_id


def _user_view(user: Any) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "active": user.active,
        "created_at": user.created_at,
    }


class IdentityUseCases:
    def __init__(
        self,
        repository: IdentityRepository,
        uow: UnitOfWork,
        settings: Settings,
        security: IdentitySecurity,
    ) -> None:
        self.repository = repository
        self.uow = uow
        self.settings = settings
        self.security = security

    async def register(self, email: str, password: str, organization_name: str) -> dict[str, Any]:
        normalized = email.strip().casefold()
        if await self.repository.user_by_email(normalized) is not None:
            raise AppError(
                "email_already_registered", "Email is already registered", status_code=409
            )
        user, organization, membership = await self.repository.create_registration(
            normalized, self.security.hash_password(password), organization_name.strip()
        )
        await self.uow.commit()
        return {
            "user": _user_view(user),
            "organization": {"id": organization.id, "name": organization.name},
            "membership": {"role": membership.role},
        }

    async def login(self, email: str, password: str) -> dict[str, Any]:
        user = await self.repository.user_by_email(email.strip().casefold())
        if (
            user is None
            or not user.active
            or not self.security.verify_password(password, user.password_hash)
        ):
            raise AppError("invalid_credentials", "Invalid email or password", status_code=401)
        return await self._issue_pair(user.id, new_id())

    async def _issue_pair(self, user_id: str, family_id: str) -> dict[str, Any]:
        access, access_expires_at = self.security.create_access_token(user_id)
        refresh = self.security.new_refresh_token()
        refresh_expires_at = datetime.now(UTC) + timedelta(
            seconds=self.settings.refresh_ttl_seconds
        )
        await self.repository.create_refresh(
            user_id, family_id, self.security.token_hash(refresh), refresh_expires_at
        )
        await self.uow.commit()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "access_expires_at": access_expires_at,
            "refresh_expires_at": refresh_expires_at,
        }

    async def refresh(self, plaintext: str) -> dict[str, Any]:
        token = await self.repository.refresh_by_hash_for_update(
            self.security.token_hash(plaintext)
        )
        now = datetime.now(UTC)
        if token is None:
            raise AppError("invalid_refresh_token", "Refresh token is invalid", status_code=401)
        if token.revoked_at is not None:
            await self.repository.revoke_family(token.family_id)
            await self.uow.commit()
            raise AppError("refresh_token_reused", "Refresh token reuse detected", status_code=401)
        if token.expires_at <= now:
            raise AppError("invalid_refresh_token", "Refresh token is invalid", status_code=401)
        access, access_expires_at = self.security.create_access_token(token.user_id)
        refresh = self.security.new_refresh_token()
        refresh_expires_at = now + timedelta(seconds=self.settings.refresh_ttl_seconds)
        replacement = await self.repository.create_refresh(
            token.user_id,
            token.family_id,
            self.security.token_hash(refresh),
            refresh_expires_at,
        )
        await self.repository.revoke_refresh(token, replacement.id)
        await self.uow.commit()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "access_expires_at": access_expires_at,
            "refresh_expires_at": refresh_expires_at,
        }

    async def logout(self, plaintext: str) -> None:
        token = await self.repository.refresh_by_hash_for_update(
            self.security.token_hash(plaintext)
        )
        if token is not None and token.revoked_at is None:
            await self.repository.revoke_refresh(token)
        await self.uow.commit()

    async def me(self, user_id: str) -> dict[str, Any]:
        user = await self.repository.user_by_id(user_id)
        if user is None or not user.active:
            raise AppError("invalid_token", "Authentication required", status_code=401)
        memberships = await self.repository.memberships(user_id)
        return {
            "user": _user_view(user),
            "memberships": [
                {"organization_id": item.organization_id, "role": item.role} for item in memberships
            ],
        }
