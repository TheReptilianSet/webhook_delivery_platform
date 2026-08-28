from __future__ import annotations

import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from webhook_platform.shared.infrastructure.metrics import HTTP_DURATION, HTTP_REQUESTS

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return REQUEST_ID.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-Id", "")
        request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else secrets.token_hex(16)
        request.state.request_id = request_id
        token = REQUEST_ID.set(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
            route = request.scope.get("route")
            route_name = getattr(route, "path", "unmatched")
            elapsed = time.monotonic() - started
            HTTP_REQUESTS.labels(
                method=request.method, route=route_name, status=str(response.status_code)
            ).inc()
            HTTP_DURATION.labels(method=request.method, route=route_name).observe(elapsed)
            structlog.get_logger("http").info(
                "request_completed",
                method=request.method,
                route=route_name,
                status=response.status_code,
                duration_ms=round(elapsed * 1000, 2),
            )
            response.headers["X-Request-Id"] = request_id
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            return response
        finally:
            structlog.contextvars.clear_contextvars()
            REQUEST_ID.reset(token)
