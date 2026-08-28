from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.shared.infrastructure.models import (
    ApiKeyModel,
    AuditEventModel,
    MembershipModel,
    OrganizationModel,
    UserModel,
)
from webhook_platform.shared.infrastructure.request_context import get_request_id


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_organization(self, organization_id: str) -> bool:
        value = await self.session.scalar(
            select(OrganizationModel.id)
            .where(OrganizationModel.id == organization_id)
            .with_for_update()
        )
        return value is not None

    async def organizations_for_user(
        self, user_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[tuple[OrganizationModel, str]]:
        query = (
            select(OrganizationModel, MembershipModel.role)
            .join(MembershipModel, MembershipModel.organization_id == OrganizationModel.id)
            .where(MembershipModel.user_id == user_id)
        )
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (OrganizationModel.created_at < created_at)
                | (
                    (OrganizationModel.created_at == created_at)
                    & (OrganizationModel.id < resource_id)
                )
            )
        result = await self.session.execute(
            query.order_by(OrganizationModel.created_at.desc(), OrganizationModel.id.desc()).limit(
                limit
            )
        )
        return list(result.tuples())

    async def organization(
        self, organization_id: str, user_id: str
    ) -> tuple[OrganizationModel, str] | None:
        result = await self.session.execute(
            select(OrganizationModel, MembershipModel.role)
            .join(MembershipModel, MembershipModel.organization_id == OrganizationModel.id)
            .where(OrganizationModel.id == organization_id, MembershipModel.user_id == user_id)
        )
        return result.tuples().one_or_none()

    async def membership(
        self, organization_id: str, user_id: str, *, lock: bool = False
    ) -> MembershipModel | None:
        query = select(MembershipModel).where(
            MembershipModel.organization_id == organization_id,
            MembershipModel.user_id == user_id,
        )
        if lock:
            query = query.with_for_update()
        return cast("MembershipModel | None", await self.session.scalar(query))

    async def members(
        self, organization_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[tuple[MembershipModel, UserModel]]:
        query = (
            select(MembershipModel, UserModel)
            .join(UserModel, UserModel.id == MembershipModel.user_id)
            .where(MembershipModel.organization_id == organization_id)
        )
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (MembershipModel.created_at < created_at)
                | ((MembershipModel.created_at == created_at) & (MembershipModel.id < resource_id))
            )
        result = await self.session.execute(
            query.order_by(MembershipModel.created_at.desc(), MembershipModel.id.desc()).limit(
                limit
            )
        )
        return list(result.tuples())

    async def user_by_email(self, email: str) -> UserModel | None:
        return cast(
            "UserModel | None",
            await self.session.scalar(select(UserModel).where(UserModel.email == email)),
        )

    async def add_membership(
        self, organization_id: str, user_id: str, role: str
    ) -> MembershipModel:
        model = MembershipModel(organization_id=organization_id, user_id=user_id, role=role)
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ValueError from exc
        return model

    async def owner_count(self, organization_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(MembershipModel)
                .where(
                    MembershipModel.organization_id == organization_id,
                    MembershipModel.role == "owner",
                )
            )
            or 0
        )

    async def delete_membership(self, membership: MembershipModel) -> None:
        await self.session.delete(membership)

    async def api_keys(
        self, organization_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[ApiKeyModel]:
        query = select(ApiKeyModel).where(ApiKeyModel.organization_id == organization_id)
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (ApiKeyModel.created_at < created_at)
                | ((ApiKeyModel.created_at == created_at) & (ApiKeyModel.id < resource_id))
            )
        result = await self.session.scalars(
            query.order_by(ApiKeyModel.created_at.desc(), ApiKeyModel.id.desc()).limit(limit)
        )
        return list(result)

    async def create_api_key(
        self,
        organization_id: str,
        name: str,
        prefix: str,
        digest: str,
        version: int,
        scopes: list[str],
    ) -> ApiKeyModel:
        model = ApiKeyModel(
            organization_id=organization_id,
            name=name,
            prefix=prefix,
            secret_digest=digest,
            digest_key_version=version,
            scopes=scopes,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def api_key(
        self, organization_id: str, key_id: str, *, lock: bool = False
    ) -> ApiKeyModel | None:
        query = select(ApiKeyModel).where(
            ApiKeyModel.organization_id == organization_id, ApiKeyModel.id == key_id
        )
        if lock:
            query = query.with_for_update()
        return cast("ApiKeyModel | None", await self.session.scalar(query))

    async def audit(
        self, organization_id: str, actor_id: str, action: str, resource_id: str | None
    ) -> None:
        self.session.add(
            AuditEventModel(
                organization_id=organization_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=action.split(".")[0],
                resource_id=resource_id,
                request_id=get_request_id(),
                safe_metadata={},
            )
        )
