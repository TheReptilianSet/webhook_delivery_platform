from __future__ import annotations

from typing import Protocol


class EndpointVerifier(Protocol):
    async def verify(
        self,
        url: str,
        endpoint_id: str,
        secret: bytes,
        challenge: str,
        verification_id: str,
    ) -> bool: ...
