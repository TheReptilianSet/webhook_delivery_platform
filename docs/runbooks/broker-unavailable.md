# Broker Unavailable

## Signal

RabbitMQ health fails, publisher confirmations fail, or pending outbox age grows while PostgreSQL and
the API remain healthy.

## Response

1. Check broker node health, disk/memory alarms, queue depth, consumers, and network reachability.
2. Leave pending outbox rows intact. The dispatcher retries with leases; do not mark messages
   published without a publisher confirmation.
3. Recover RabbitMQ using the broker operator procedure. Avoid deleting/redeclaring production
   queues unless their durable arguments are verified against the application configuration.
4. Confirm the delivery queue, dead-letter exchange/queue, publisher confirms, and an active worker.
5. Watch oldest pending outbox age and queue depth return to baseline; expect possible duplicates in
   the publish-confirm uncertainty window.

## Escalate

Escalate for quorum/data loss, persistent declaration mismatch, disk alarm, or an outbox backlog that
cannot drain within the incident objective.
