from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from webhook_platform.shared.domain.errors import AppError

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class RequestBodyLimitMiddleware:
    def __init__(self, app: Any, *, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/api/v1/events":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.limit:
                    await self._reject(scope, send)
                    return
            except ValueError:
                await self._reject(scope, send)
                return
        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise AppError("event_too_large", "Event body is too large", status_code=413)
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope: dict[str, Any], send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id", "unknown")
        body = json.dumps(
            {
                "error": {
                    "code": "event_too_large",
                    "message": "Event body is too large",
                    "request_id": request_id,
                    "details": {},
                }
            },
            separators=(",", ":"),
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", str(request_id).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
