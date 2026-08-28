from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.api_dependencies import current_user_id, get_session, settings_from
from webhook_platform.organizations.api.schemas import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyResponse,
    MemberCreateRequest,
    MemberResponse,
    MemberUpdateRequest,
    OrganizationResponse,
)
from webhook_platform.organizations.application.use_cases import OrganizationUseCases
from webhook_platform.organizations.infrastructure.repository import (
    SqlAlchemyOrganizationRepository,
)
from webhook_platform.shared.api.schemas import PageResponse
from webhook_platform.shared.domain.pagination import decode_cursor, encode_cursor
from webhook_platform.shared.infrastructure.security import DefaultApiKeyIssuer
from webhook_platform.shared.infrastructure.uow import SqlAlchemyUnitOfWork

router = APIRouter(tags=["organizations"])


def use_cases(request: Request, session: AsyncSession) -> OrganizationUseCases:
    settings = settings_from(request)
    return OrganizationUseCases(
        SqlAlchemyOrganizationRepository(session),
        SqlAlchemyUnitOfWork(session),
        settings,
        DefaultApiKeyIssuer(settings),
    )


@router.get("/organizations", response_model=PageResponse[OrganizationResponse])
async def list_organizations(
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, next_item = await use_cases(request, session).list_organizations(
        user_id, decode_cursor(cursor), limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.get("/organizations/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).get_organization(organization_id, user_id)


@router.get("/organizations/{organization_id}/members", response_model=PageResponse[MemberResponse])
async def list_members(
    organization_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, next_item = await use_cases(request, session).list_members(
        organization_id, user_id, decode_cursor(cursor), limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.post(
    "/organizations/{organization_id}/members", status_code=201, response_model=MemberResponse
)
async def add_member(
    organization_id: str,
    body: MemberCreateRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).add_member(
        organization_id, user_id, body.email, body.role
    )


@router.patch(
    "/organizations/{organization_id}/members/{target_user_id}", response_model=MemberResponse
)
async def update_member(
    organization_id: str,
    target_user_id: str,
    body: MemberUpdateRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).change_member(
        organization_id, user_id, target_user_id, body.role
    )


@router.delete("/organizations/{organization_id}/members/{target_user_id}", status_code=204)
async def delete_member(
    organization_id: str,
    target_user_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await use_cases(request, session).remove_member(organization_id, user_id, target_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/organizations/{organization_id}/api-keys", response_model=PageResponse[ApiKeyResponse]
)
async def list_api_keys(
    organization_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, next_item = await use_cases(request, session).list_api_keys(
        organization_id, user_id, decode_cursor(cursor), limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.post(
    "/organizations/{organization_id}/api-keys",
    status_code=201,
    response_model=ApiKeyCreatedResponse,
)
async def create_api_key(
    organization_id: str,
    body: ApiKeyCreateRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).create_key(
        organization_id, user_id, body.name, list(body.scopes)
    )


@router.delete("/organizations/{organization_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    organization_id: str,
    key_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await use_cases(request, session).revoke_key(organization_id, user_id, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
