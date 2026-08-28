from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from webhook_platform.config.settings import Settings
from webhook_platform.shared.application.api_keys import ApiKeyIssuer
from webhook_platform.shared.application.ports import UnitOfWork
from webhook_platform.shared.domain.errors import AppError, ForbiddenError, NotFoundError


class OrganizationRepository(Protocol):
    async def lock_organization(self, organization_id: str) -> bool: ...

    async def organizations_for_user(
        self, user_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[Any]: ...

    async def organization(self, organization_id: str, user_id: str) -> Any | None: ...

    async def membership(
        self, organization_id: str, user_id: str, *, lock: bool = False
    ) -> Any | None: ...

    async def members(
        self, organization_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[Any]: ...

    async def user_by_email(self, email: str) -> Any | None: ...

    async def add_membership(self, organization_id: str, user_id: str, role: str) -> Any: ...

    async def owner_count(self, organization_id: str) -> int: ...

    async def delete_membership(self, membership: Any) -> None: ...

    async def api_keys(
        self, organization_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[Any]: ...

    async def create_api_key(
        self,
        organization_id: str,
        name: str,
        prefix: str,
        digest: str,
        version: int,
        scopes: list[str],
    ) -> Any: ...

    async def api_key(
        self, organization_id: str, key_id: str, *, lock: bool = False
    ) -> Any | None: ...

    async def audit(
        self, organization_id: str, actor_id: str, action: str, resource_id: str | None
    ) -> None: ...


class OrganizationUseCases:
    def __init__(
        self,
        repository: OrganizationRepository,
        uow: UnitOfWork,
        settings: Settings,
        api_key_issuer: ApiKeyIssuer,
    ) -> None:
        self.repository = repository
        self.uow = uow
        self.settings = settings
        self.api_key_issuer = api_key_issuer

    async def require_role(self, organization_id: str, user_id: str, roles: set[str]) -> Any:
        membership = await self.repository.membership(organization_id, user_id)
        if membership is None:
            raise NotFoundError()
        if membership.role not in roles:
            raise ForbiddenError()
        return membership

    async def list_organizations(
        self, user_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> tuple[list[dict[str, Any]], Any | None]:
        rows = await self.repository.organizations_for_user(user_id, cursor, limit + 1)
        next_item = rows[limit - 1][0] if len(rows) > limit else None
        return [
            {"id": org.id, "name": org.name, "status": org.status, "role": role}
            for org, role in rows[:limit]
        ], next_item

    async def get_organization(self, organization_id: str, user_id: str) -> dict[str, Any]:
        row = await self.repository.organization(organization_id, user_id)
        if row is None:
            raise NotFoundError()
        org, role = row
        return {"id": org.id, "name": org.name, "status": org.status, "role": role}

    async def list_members(
        self,
        organization_id: str,
        user_id: str,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        await self.require_role(organization_id, user_id, {"owner", "admin", "member"})
        rows = await self.repository.members(organization_id, cursor, limit + 1)
        next_item = rows[limit - 1][0] if len(rows) > limit else None
        return [
            {"user_id": user.id, "email": user.email, "role": membership.role}
            for membership, user in rows[:limit]
        ], next_item

    async def add_member(
        self, organization_id: str, actor_id: str, email: str, role: str
    ) -> dict[str, Any]:
        if not await self.repository.lock_organization(organization_id):
            raise NotFoundError()
        await self.require_role(organization_id, actor_id, {"owner"})
        if role not in {"owner", "admin", "member"}:
            raise AppError("invalid_role", "Role is invalid", status_code=422)
        user = await self.repository.user_by_email(email.strip().casefold())
        if user is None:
            raise NotFoundError()
        try:
            membership = await self.repository.add_membership(organization_id, user.id, role)
        except ValueError as exc:
            raise AppError(
                "membership_exists", "Membership already exists", status_code=409
            ) from exc
        await self.repository.audit(organization_id, actor_id, "membership.created", membership.id)
        await self.uow.commit()
        return {"user_id": user.id, "email": user.email, "role": role}

    async def change_member(
        self, organization_id: str, actor_id: str, target_user_id: str, role: str
    ) -> dict[str, Any]:
        if not await self.repository.lock_organization(organization_id):
            raise NotFoundError()
        await self.require_role(organization_id, actor_id, {"owner"})
        membership = await self.repository.membership(organization_id, target_user_id, lock=True)
        if membership is None:
            raise NotFoundError()
        if (
            membership.role == "owner"
            and role != "owner"
            and await self.repository.owner_count(organization_id) <= 1
        ):
            raise AppError("last_owner", "Organization must retain an owner", status_code=409)
        if role not in {"owner", "admin", "member"}:
            raise AppError("invalid_role", "Role is invalid", status_code=422)
        membership.role = role
        await self.repository.audit(organization_id, actor_id, "membership.updated", membership.id)
        await self.uow.commit()
        return {"user_id": target_user_id, "role": role}

    async def remove_member(self, organization_id: str, actor_id: str, target_user_id: str) -> None:
        if not await self.repository.lock_organization(organization_id):
            raise NotFoundError()
        await self.require_role(organization_id, actor_id, {"owner"})
        membership = await self.repository.membership(organization_id, target_user_id, lock=True)
        if membership is None:
            raise NotFoundError()
        if membership.role == "owner" and await self.repository.owner_count(organization_id) <= 1:
            raise AppError("last_owner", "Organization must retain an owner", status_code=409)
        resource_id = membership.id
        await self.repository.delete_membership(membership)
        await self.repository.audit(organization_id, actor_id, "membership.deleted", resource_id)
        await self.uow.commit()

    async def list_api_keys(
        self,
        organization_id: str,
        user_id: str,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        await self.require_role(organization_id, user_id, {"owner", "admin"})
        rows = await self.repository.api_keys(organization_id, cursor, limit + 1)
        next_item = rows[limit - 1] if len(rows) > limit else None
        return [self._key_view(item) for item in rows[:limit]], next_item

    async def create_key(
        self, organization_id: str, user_id: str, name: str, scopes: list[str]
    ) -> dict[str, Any]:
        await self.require_role(organization_id, user_id, {"owner", "admin"})
        if sorted(set(scopes)) != ["events:write"]:
            raise AppError("invalid_scope", "API key scopes are invalid", status_code=422)
        plaintext, prefix, digest = self.api_key_issuer.issue()
        model = await self.repository.create_api_key(
            organization_id,
            name.strip(),
            prefix,
            digest,
            self.settings.api_key_digest_version,
            scopes,
        )
        await self.repository.audit(organization_id, user_id, "api_key.created", model.id)
        await self.uow.commit()
        return {**self._key_view(model), "key": plaintext}

    async def revoke_key(self, organization_id: str, user_id: str, key_id: str) -> None:
        from datetime import UTC, datetime

        await self.require_role(organization_id, user_id, {"owner", "admin"})
        key = await self.repository.api_key(organization_id, key_id, lock=True)
        if key is not None and key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            await self.repository.audit(organization_id, user_id, "api_key.revoked", key.id)
        await self.uow.commit()

    @staticmethod
    def _key_view(item: Any) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "prefix": item.prefix,
            "scopes": item.scopes,
            "revoked_at": item.revoked_at,
            "created_at": item.created_at,
        }
