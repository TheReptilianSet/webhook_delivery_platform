# Receiver Failure Storm

## Signal

Retry scheduling, `429`/`5xx`, network failures, or dead-letter transitions rise sharply for one or
more endpoints.

## Response

1. Identify affected organizations and endpoint counts internally without exposing URLs or tenant
   identifiers as metric labels.
2. Confirm whether the receiver advertises a bounded `Retry-After`. Do not bypass TLS, SSRF policy,
   retry limits, or endpoint concurrency limits.
3. Ask an owner/admin to disable a persistently failing endpoint when retries threaten shared
   capacity. Disabling cancels waiting work; an in-flight request may still finish.
4. Monitor worker utilization, scheduled retries, outbox lag, and dead-letter growth. Apply ingress
   backpressure rather than increasing attempts.
5. After receiver recovery, verify the endpoint and use explicit idempotent replay for selected
   terminal deliveries. Receivers must deduplicate by event ID.

## Escalate

Escalate for cross-tenant starvation, retry amplification, unexpected private-address resolution, or
evidence that concurrency counters are stuck.
