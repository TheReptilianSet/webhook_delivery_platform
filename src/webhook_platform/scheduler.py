from __future__ import annotations

import argparse
import asyncio

import structlog

from webhook_platform.config.settings import get_settings
from webhook_platform.maintenance.application.cleanup import cleanup_expired
from webhook_platform.maintenance.application.reconcile import reconcile_stale, schedule_due
from webhook_platform.shared.infrastructure.database import create_engine, create_session_factory
from webhook_platform.shared.infrastructure.logging import configure_logging
from webhook_platform.shared.infrastructure.metrics import CLEANUP_ROWS


async def run(*, once: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = structlog.get_logger("scheduler")
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    iteration = 0
    try:
        while True:
            await reconcile_stale(factory, settings)
            await schedule_due(factory, settings)
            if iteration % 3600 == 0:
                cleaned = await cleanup_expired(factory, settings)
                if cleaned:
                    CLEANUP_ROWS.inc(cleaned)
                    logger.info("retention_cleanup_completed", affected_rows=cleaned)
            iteration += 1
            if once:
                return
            await asyncio.sleep(1)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(once=args.once))


if __name__ == "__main__":
    main()
