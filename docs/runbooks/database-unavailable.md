# Database Unavailable

## Signal

API readiness returns `503`, process logs report PostgreSQL connection failures, and queue workers
cannot claim or finalize deliveries.

## Response

1. Confirm scope with `/health/live`, `/health/ready`, PostgreSQL health, connection saturation, disk
   space, and recent infrastructure changes. Do not include connection strings in incident notes.
2. Stop traffic at the load balancer if repeated writes are overwhelming recovery. Do not acknowledge
   delivery commands manually: RabbitMQ redelivery and the reconciler preserve at-least-once behavior.
3. Restore PostgreSQL availability using the database operator's documented failover or restore
   procedure. Never run migrations against an unidentified database.
4. Verify `SELECT 1`, migration revision, API readiness, outbox lag, stale leases, and delivery state
   transitions before restoring normal traffic.
5. Reconcile any uncertainty-window duplicates with receiver evidence; never rewrite attempt history.

## Escalate

Escalate immediately for suspected corruption, unavailable backups, a migration mismatch, or data
loss. Preserve logs with request/correlation IDs but no payloads, URLs, tokens, or secrets.
