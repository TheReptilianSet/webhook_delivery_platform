# Outbox Lag

## Signal

The oldest pending outbox message age or pending count increases while event ingestion continues.

## Response

1. Separate database contention, dispatcher failure, broker failure, and insufficient publish
   throughput using health checks and low-cardinality metrics.
2. Verify dispatcher instances, lease expiry, recent errors, database pool saturation, and RabbitMQ
   confirms. Do not clear leases or update rows by hand during normal recovery.
3. If dependencies are healthy, restart only the dispatcher role and confirm expired leases are
   reclaimed. Scale only after measuring database and broker headroom.
4. If the organization backlog limit rejects ingestion, preserve the `429` safeguard until the
   backlog drains.
5. Confirm the oldest age and pending count fall continuously, then document peak lag and cause.

## Escalate

Escalate for non-expiring leases, repeated publish uncertainty, database lock contention, or backlog
growth after dispatcher capacity is restored.
