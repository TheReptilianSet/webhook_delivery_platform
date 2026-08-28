from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.api_dependencies import current_user_id, get_session, settings_from
from webhook_platform.endpoints.api.schemas import (
    EndpointCreatedResponse,
    EndpointCreateRequest,
    EndpointResponse,
    EndpointUpdateRequest,
)
from webhook_platform.endpoints.application.use_cases import EndpointUseCases
from webhook_platform.endpoints.infrastructure.network import resolve_and_validate
from webhook_platform.endpoints.infrastructure.repository import SqlAlchemyEndpointRepository
from webhook_platform.endpoints.infrastructure.verifier import HttpEndpointVerifier
from webhook_platform.shared.api.schemas import PageResponse
from webhook_platform.shared.domain.pagination import decode_cursor, encode_cursor
from webhook_platform.shared.infrastructure.security import AesGcmCipher
from webhook_platform.shared.infrastructure.uow import SqlAlchemyUnitOfWork

router = APIRouter(tags=["endpoints"])


def use_cases(request: Request, session: AsyncSession) -> EndpointUseCases:
    settings = settings_from(request)
    return EndpointUseCases(
        SqlAlchemyEndpointRepository(session),
        SqlAlchemyUnitOfWork(session),
        settings,
        AesGcmCipher(settings),
        HttpEndpointVerifier(request.app.state.container.http, settings),
        resolve_and_validate,
    )


@router.post(
    "/organizations/{organization_id}/endpoints",
    status_code=201,
    response_model=EndpointCreatedResponse,
)
async def create_endpoint(
    organization_id: str,
    body: EndpointCreateRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).create(
        organization_id, user_id, body.name, body.url, body.event_types
    )


@router.get(
    "/organizations/{organization_id}/endpoints", response_model=PageResponse[EndpointResponse]
)
async def list_endpoints(
    organization_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, next_item = await use_cases(request, session).list(
        organization_id, user_id, decode_cursor(cursor), limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.get(
    "/organizations/{organization_id}/endpoints/{endpoint_id}", response_model=EndpointResponse
)
async def get_endpoint(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).get(organization_id, user_id, endpoint_id)


@router.patch(
    "/organizations/{organization_id}/endpoints/{endpoint_id}", response_model=EndpointResponse
)
async def update_endpoint(
    organization_id: str,
    endpoint_id: str,
    body: EndpointUpdateRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).update(
        organization_id, user_id, endpoint_id, body.model_dump(exclude_unset=True)
    )


@router.post(
    "/organizations/{organization_id}/endpoints/{endpoint_id}/verify",
    response_model=EndpointResponse,
)
async def verify_endpoint(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).verify(organization_id, user_id, endpoint_id)


@router.delete("/organizations/{organization_id}/endpoints/{endpoint_id}", status_code=204)
async def delete_endpoint(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await use_cases(request, session).delete(organization_id, user_id, endpoint_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
