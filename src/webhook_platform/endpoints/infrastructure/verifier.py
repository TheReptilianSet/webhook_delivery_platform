from __future__ import annotations

import asyncio
import hmac
import json
from datetime import UTC, datetime

import httpx

from webhook_platform.config.settings import Settings
from webhook_platform.shared.infrastructure.security import verification_signature


class HttpEndpointVerifier:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def verify(
        self,
        url: str,
        endpoint_id: str,
        secret: bytes,
        challenge: str,
        verification_id: str,
    ) -> bool:
        timestamp = str(int(datetime.now(UTC).timestamp()))
        body = json.dumps(
            {"challenge": challenge, "endpoint_id": endpoint_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "Webhook-Verification-Id": verification_id,
            "Webhook-Timestamp": timestamp,
            "Webhook-Verification-Signature": verification_signature(
                secret, timestamp, verification_id, body
            ),
        }
        try:
            async with asyncio.timeout(self.settings.http_total_timeout):
                response = await self.client.post(url, content=body, headers=headers)
        except (TimeoutError, httpx.HTTPError):
            return False
        return 200 <= response.status_code < 300 and hmac.compare_digest(
            response.headers.get("Webhook-Verification", ""), challenge
        )
