from __future__ import annotations

import asyncio
import socket

from webhook_platform.endpoints.domain.network import ValidatedDestination, is_public_address
from webhook_platform.shared.domain.errors import AppError


async def resolve_and_validate(destination: ValidatedDestination) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(
            destination.host, destination.port, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise AppError(
            "unsafe_destination", "Endpoint destination cannot be resolved", status_code=422
        ) from exc
    addresses = tuple(sorted({str(record[4][0]) for record in records}))
    if not addresses or any(not is_public_address(value) for value in addresses):
        raise AppError("unsafe_destination", "Endpoint destination is not public", status_code=422)
    return addresses
