from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from celery import Celery
from kombu import Connection, Exchange, Producer, Queue

from webhook_platform.config.settings import Settings
from webhook_platform.shared.domain.ids import new_id


class RabbitPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.celery = Celery("webhook_platform_dispatcher", broker=settings.broker_url)
        self.celery.conf.update(task_serializer="json", accept_content=["json"])
        self.exchange = Exchange(settings.broker_exchange, type="direct", durable=True)
        self.dlx = Exchange(settings.broker_dlx, type="direct", durable=True)
        self.queue = Queue(
            settings.broker_queue,
            exchange=self.exchange,
            routing_key=settings.broker_routing_key,
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": settings.broker_dlx,
                "x-dead-letter-routing-key": "delivery.dead.v1",
            },
        )
        self.dead_queue = Queue(
            settings.broker_dead_queue,
            exchange=self.dlx,
            routing_key="delivery.dead.v1",
            durable=True,
        )

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        with Connection(
            self.settings.broker_url,
            transport_options={"confirm_publish": True},
        ) as connection:
            self.exchange(connection).declare()
            self.dlx(connection).declare()
            self.queue(connection).declare()
            self.dead_queue(connection).declare()
            yield connection

    def publish(self, connection: Connection, payload: dict[str, Any]) -> None:
        producer = Producer(connection)
        message = self.celery.amqp.create_task_message(
            task_id=new_id(),
            name="delivery.execute.v1",
            kwargs=payload,
            ignore_result=True,
        )
        self.celery.amqp.send_task_message(
            producer,
            "delivery.execute.v1",
            message,
            exchange=self.exchange,
            routing_key=self.settings.broker_routing_key,
            queue=self.queue,
            delivery_mode=2,
            mandatory=True,
            retry=False,
            declare=[self.exchange, self.queue],
        )
