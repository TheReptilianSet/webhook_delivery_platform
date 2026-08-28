from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.shared.infrastructure.models import (
    MembershipModel,
    OrganizationModel,
    RefreshTokenModel,
    UserModel,
)


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_by_email(self, email: str) -> UserModel | None:
        return cast(
            "UserModel | None",
            await self.session.scalar(select(UserModel).where(UserModel.email == email)),
        )

    async def user_by_id(self, user_id: str) -> UserModel | None:
        return await self.session.get(UserModel, user_id)

    async def create_registration(
        self, email: str, password_hash: str, organization_name: str
    ) -> tuple[UserModel, OrganizationModel, MembershipModel]:
        user = UserModel(email=email, password_hash=password_hash)
        organization = OrganizationModel(name=organization_name)
        self.session.add_all([user, organization])
        await self.session.flush()
        membership = MembershipModel(organization_id=organization.id, user_id=user.id, role="owner")
        self.session.add(membership)
        await self.session.flush()
        return user, organization, membership

    async def create_refresh(
        self, user_id: str, family_id: str, digest: str, expires_at: datetime
    ) -> RefreshTokenModel:
        token = RefreshTokenModel(
            user_id=user_id, family_id=family_id, token_hash=digest, expires_at=expires_at
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def refresh_by_hash_for_update(self, digest: str) -> RefreshTokenModel | None:
        return cast(
            "RefreshTokenModel | None",
            await self.session.scalar(
                select(RefreshTokenModel)
                .where(RefreshTokenModel.token_hash == digest)
                .with_for_update()
            ),
        )

    async def revoke_refresh(
        self, token: RefreshTokenModel, replaced_by_id: str | None = None
    ) -> None:
        token.revoked_at = datetime.now(UTC)
        token.replaced_by_id = replaced_by_id

    async def revoke_family(self, family_id: str) -> None:
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.family_id == family_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )

    async def memberships(self, user_id: str) -> list[MembershipModel]:
        result = await self.session.scalars(
            select(MembershipModel).where(MembershipModel.user_id == user_id)
        )
        return list(result)
