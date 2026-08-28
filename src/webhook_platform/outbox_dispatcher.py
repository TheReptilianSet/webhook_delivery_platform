from __future__ import annotations

import argparse
import asyncio
import signal
from contextlib import suppress

import structlog

from webhook_platform.config.settings import get_settings
from webhook_platform.outbox.infrastructure.publisher import RabbitPublisher
from webhook_platform.outbox.infrastructure.repository import claim_outbox, finish_outbox
from webhook_platform.shared.infrastructure.database import create_engine, create_session_factory
from webhook_platform.shared.infrastructure.logging import configure_logging
from webhook_platform.shared.infrastructure.metrics import OUTBOX_PUBLISH


async def run(*, once: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = structlog.get_logger("outbox_dispatcher")
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    publisher = RabbitPublisher(settings)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stopping.set)
    try:
        while not stopping.is_set():
            rows = await claim_outbox(factory, settings.outbox_batch_size)
            if rows:
                try:
                    with publisher.connection() as connection:
                        for row in rows:
                            try:
                                await asyncio.to_thread(
                                    publisher.publish, connection, row["payload"]
                                )
                            except Exception as exc:
                                logger.warning(
                                    "outbox_publish_failed", error_type=type(exc).__name__
                                )
                                OUTBOX_PUBLISH.labels(result="failed").inc()
                                await finish_outbox(
                                    factory, row["id"], published=False, error=type(exc).__name__
                                )
                            else:
                                OUTBOX_PUBLISH.labels(result="confirmed").inc()
                                await finish_outbox(factory, row["id"], published=True)
                except Exception as exc:
                    logger.warning(
                        "broker_connection_failed",
                        error_type=type(exc).__name__,
                        batch_size=len(rows),
                    )
                    OUTBOX_PUBLISH.labels(result="connection_failed").inc(len(rows))
                    for row in rows:
                        await finish_outbox(
                            factory, row["id"], published=False, error=type(exc).__name__
                        )
            if once:
                break
            with suppress(TimeoutError):
                await asyncio.wait_for(stopping.wait(), timeout=0.5)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(once=args.once))


if __name__ == "__main__":
    main()
