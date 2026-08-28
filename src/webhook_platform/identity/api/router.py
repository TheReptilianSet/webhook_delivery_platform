from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.api_dependencies import current_user_id, get_session, settings_from
from webhook_platform.identity.api.schemas import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    RegistrationResponse,
    TokenResponse,
)
from webhook_platform.identity.application.use_cases import IdentityUseCases
from webhook_platform.identity.infrastructure.repository import SqlAlchemyIdentityRepository
from webhook_platform.identity.infrastructure.security import DefaultIdentitySecurity
from webhook_platform.shared.infrastructure.uow import SqlAlchemyUnitOfWork

router = APIRouter(tags=["identity"])


def use_cases(request: Request, session: AsyncSession) -> IdentityUseCases:
    settings = settings_from(request)
    return IdentityUseCases(
        SqlAlchemyIdentityRepository(session),
        SqlAlchemyUnitOfWork(session),
        settings,
        DefaultIdentitySecurity(settings),
    )


@router.post("/auth/register", status_code=201, response_model=RegistrationResponse)
async def register(
    body: RegisterRequest, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    return await use_cases(request, session).register(
        body.email, body.password, body.organization_name
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    client_ip = request.client.host if request.client else "unknown"
    settings = settings_from(request)
    await request.app.state.container.rate_limiter.require(
        f"login:{client_ip}:{body.email.lower()}",
        rate=settings.login_rate_per_minute / 60,
        capacity=settings.login_rate_per_minute,
    )
    return await use_cases(request, session).login(body.email, body.password)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    return await use_cases(request, session).refresh(body.refresh_token)


@router.post("/auth/logout", status_code=204)
async def logout(
    body: LogoutRequest, request: Request, session: AsyncSession = Depends(get_session)
) -> Response:
    await use_cases(request, session).logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).me(user_id)
