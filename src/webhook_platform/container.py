from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from webhook_platform.config.settings import Settings
from webhook_platform.shared.infrastructure.database import create_engine, create_session_factory
from webhook_platform.shared.infrastructure.rate_limit import InMemoryRateLimiter


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: AsyncEngine = create_engine(settings)
        self.sessions: async_sessionmaker[AsyncSession] = create_session_factory(self.engine)
        self.rate_limiter = InMemoryRateLimiter()
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.http_connect_timeout,
                read=settings.http_read_timeout,
                write=settings.http_write_timeout,
                pool=settings.http_pool_timeout,
            ),
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self.http.aclose()
        await self.engine.dispose()
