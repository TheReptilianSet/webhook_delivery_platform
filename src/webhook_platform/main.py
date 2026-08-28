from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from kombu import Connection
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.middleware.cors import CORSMiddleware

from webhook_platform.config.settings import Settings, get_settings
from webhook_platform.container import Container
from webhook_platform.deliveries.api.router import router as deliveries_router
from webhook_platform.endpoints.api.router import router as endpoints_router
from webhook_platform.events.api.router import router as events_router
from webhook_platform.identity.api.router import router as identity_router
from webhook_platform.organizations.api.router import router as organizations_router
from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.infrastructure.body_limit import RequestBodyLimitMiddleware
from webhook_platform.shared.infrastructure.logging import configure_logging
from webhook_platform.shared.infrastructure.request_context import RequestIdMiddleware


def broker_ping(url: str, timeout: float) -> None:
    with Connection(url, connect_timeout=timeout) as connection:
        connection.connect()


def error_payload(
    request: Request, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", "unknown"),
            "details": details or {},
        }
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = Container(resolved)
        yield
        await app.state.container.close()

    app = FastAPI(title="Webhook Delivery Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestBodyLimitMiddleware, limit=resolved.event_body_limit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_allow_origins),
        allow_origin_regex=(
            r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
            if resolved.allow_local_browser_origins
            else None
        ),
        allow_credentials=resolved.cors_allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["Idempotency-Replayed", "X-Request-Id"],
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        headers = (
            {"Retry-After": str(exc.details["retry_after"])}
            if "retry_after" in exc.details
            else None
        )
        return JSONResponse(
            error_payload(request, exc.code, exc.message, exc.details),
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = {
            "fields": [
                {"location": list(item["loc"]), "type": item["type"]} for item in exc.errors()
            ]
        }
        return JSONResponse(
            error_payload(request, "validation_error", "Request validation failed", details),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            error_payload(request, "internal_error", "Internal server error"), status_code=500
        )

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request) -> JSONResponse:
        try:
            async with request.app.state.container.sessions() as session:
                await session.execute(text("SELECT 1"))
            await asyncio.wait_for(
                asyncio.to_thread(
                    broker_ping,
                    resolved.broker_url,
                    resolved.publisher_confirm_timeout_seconds,
                ),
                timeout=resolved.publisher_confirm_timeout_seconds,
            )
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    for router in (
        identity_router,
        organizations_router,
        endpoints_router,
        events_router,
        deliveries_router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
