---
type: project-specification
status: active
product: "Webhook Delivery Platform"
version: "0.1.0"
approved_for: product_development
last_reviewed: 2026-08-28
---

# Webhook Delivery Platform — Active Project Specification v0.1

## 1. Implementation mandate

This document defines the active product behavior and Definition of Done. The service is maintained
as a standalone SaaS component for asynchronous media-processing pipelines. Product changes must
preserve the contracts below and must not introduce an alternative broker, cache, embedded UI, or
calls to unapproved external endpoints. The Web, iOS, and Android client remains a separate project
at <https://github.com/TheReptilianSet/webhook_delivery_platform>.

## 2. Product outcome

The multi-tenant SaaS accepts media job lifecycle events through a scoped organization API key,
atomically stores the event, deliveries, and outbox rows, and asynchronously sends a signed HTTP POST
to each verified endpoint. It records immutable attempts, retries transient failures, moves exhausted
deliveries to `dead_lettered`, and supports idempotent manual replay.

Public README должен объяснять прикладные кейсы:

- video transcoding and rendition completion callbacks;
- AI image, video, and audio generation status updates;
- moderation, transcription, and media-analysis results;
- thumbnail, preview, waveform, and proxy generation events;
- large media import, export, and archive completion.

Публичная гарантия — at-least-once. Receiver обязан дедуплицировать по stable event ID. Exactly-once и ordering не обещаются.

## 3. Scope

- email/password auth, refresh rotation/revocation;
- organization and `owner|admin|member` memberships;
- `events:write` organization API keys shown once;
- endpoint + exact subscriptions + live verification;
- idempotent event ingest, canonical JSON and transactional outbox;
- RabbitMQ command delivery with publisher confirms/manual ack;
- HMAC-SHA256 outbound POST and SSRF-safe HTTP;
- durable DB retry schedule, stale lease reconciliation, DLQ and replay;
- attempt/audit evidence, encryption, limits and cleanup;
- health/readiness/metrics/logs, migrations, CI, and a Compose local acceptance receiver;
- unit/API/integration/security/e2e tests and English public documentation.

## 4. Non-goals

No embedded dashboard/UI, invitations/email, billing, transformations, wildcard subscriptions,
custom headers/methods/ports/CA/mTLS, private endpoints, secret rotation, exactly-once/ordering,
Kafka/Redis/Kubernetes/microservices/multi-region, or production deployment. Web, iOS, and Android
interfaces are supplied by the separate client project and are outside this backend's runtime and
release scope.

## 5. Actors and permissions

| Actor | Access |
| --- | --- |
| Anonymous | register/login/docs/liveness |
| Owner | all org resources, membership roles, keys, endpoint management, replay |
| Admin | keys/endpoints/subscriptions, read journal, replay; no owner management |
| Member | read-only organization resources/journal |
| Producer | API key with `events:write`; event ingestion only |
| Receiver | responds to challenge and verifies signed delivery |

Every tenant-owned query includes `organization_id`; cross-tenant UUID access returns `404 resource_not_found`. At least one owner must remain. Security actions create audit rows.

## 6. Domain invariants

### Identity/idempotency

- Event, key, endpoint, subscription, delivery, attempt belong to exactly one organization.
- Event ID remains stable across all deliveries/attempts/replay and is receiver deduplication key.
- Producer idempotency identity is `(organization_id, api_key_id, Idempotency-Key)`.
- Same key + same canonical fingerprint returns original event and no new deliveries.
- Same key + different type/version/body returns `409 idempotency_conflict`.
- Manual replay creates a new delivery ID linked through `replay_of`; original history is immutable.

### Durability

- PostgreSQL is product source of truth; RabbitMQ message contains resource ID only.
- Event, matching original deliveries and outbox rows commit in one transaction.
- Outbox publish may duplicate around confirm/DB commit; worker is idempotent.
- Crash after receiver side effect but before DB commit may cause another HTTP request. This uncertainty is explicitly recorded and documented.
- Attempt rows are append-only.

### Endpoint/network

- Production URL: absolute HTTPS, port 443, no userinfo/fragment, all resolved A/AAAA public.
- Reject private, loopback, link-local, unspecified, multicast, reserved, documentation/benchmark, metadata and IPv4-mapped unsafe IPv6 ranges.
- Validate at create/update and directly before each connection; reject if any resolved address is unsafe.
- Redirects disabled; `3xx` is terminal. TLS verification enabled.
- Local `http://test-receiver:8080` exists only in development/test exact allowlist; production starts with error if exception is enabled.
- Endpoint must pass one-time challenge before active delivery.

### Secrets/signature

- API key: 256-bit CSPRNG secret, one-time display, lookup prefix + versioned HMAC-SHA256 digest under a distinct runtime pepper; constant-time comparison. Argon2id is used only for passwords.
- Webhook secret: CSPRNG, one-time display, AES-256-GCM ciphertext with unique nonce/key version/endpoint ID AAD.
- Response preview encrypted equivalently with delivery/attempt AAD.
- Master encryption key and JWT secret are separate runtime secrets.
- Exact canonical body bytes are stored, signed and sent; never reserialize for delivery.
- Signature input UTF-8: `timestamp + "." + event_id + "." + delivery_id + "." + raw_body`.
- Header: `Webhook-Signature: v1=<lowercase HMAC-SHA256 hex>`.

## 7. API-wide contract

Base `/api/v1`, JSON, opaque UUIDv7-compatible IDs, UTC RFC 3339 timestamps, request ID response header. Error:

```json
{"error":{"code":"stable_code","message":"Safe message","request_id":"01...","details":{}}}
```

No traceback/internal exception/secrets. Lists use opaque keyset cursor `(created_at,id)`, default 50/max 100.

### 7.1. Identity

- `POST /auth/register` `{email,password,organization_name}` → `201` user + organization + owner membership.
- `POST /auth/login` → access/refresh; invalid credentials have one generic error.
- `POST /auth/refresh` rotates token/family; reuse revokes family.
- `POST /auth/logout` idempotently revokes, `204`.
- `GET /me` returns user and memberships.

Password 12–128 Unicode chars, normalized unique email, Argon2id. Access TTL 15 min, refresh TTL 30 days; refresh stored only as hash.

### 7.2. Organizations/members

- `GET /organizations`; `GET /organizations/{org_id}`.
- `GET /organizations/{org_id}/members`.
- `POST /organizations/{org_id}/members` owner only, `{email,role}`; user must already exist.
- `PATCH /organizations/{org_id}/members/{user_id}` owner only.
- `DELETE /organizations/{org_id}/members/{user_id}` owner only.

Roles are owner/admin/member; cannot remove/demote last owner.

### 7.3. API keys

- `POST /organizations/{org_id}/api-keys` owner/admin, `{name,scopes:["events:write"]}` → metadata + plaintext once.
- `GET /organizations/{org_id}/api-keys` metadata, never secret/hash.
- `DELETE /organizations/{org_id}/api-keys/{id}` idempotent revoke, `204`.

Authorization: `Bearer whk_live_<prefix>.<secret>`; development may use `whk_test_`, production rejects it.

### 7.4. Endpoints

Create body:

```json
{"name":"Media processing receiver","url":"https://receiver.example.com/webhooks","event_types":["media.processing.completed"]}
```

- `POST /organizations/{org_id}/endpoints` owner/admin → `201`, `pending_verification`, signing secret once.
- `GET /organizations/{org_id}/endpoints` and `/{id}` member.
- `PATCH /organizations/{org_id}/endpoints/{id}` owner/admin; URL change re-enters pending verification; supports enabled/name/event types.
- `POST /organizations/{org_id}/endpoints/{id}/verify` owner/admin → active or `422 verification_failed`.
- `DELETE /organizations/{org_id}/endpoints/{id}` soft delete/cancel waiting deliveries, `204`.

Name 1–100, URL <=2048, 1–50 unique exact event types. Event type regex `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`, max 128.

Every verify call generates a CSPRNG challenge, stores only its hash/10-minute expiry and immediately sends POST JSON `{"challenge":"...","endpoint_id":"..."}`. Headers are `Webhook-Verification-Id`, `Webhook-Timestamp` and `Webhook-Verification-Signature: v1=<hex>`; HMAC input is `timestamp + "." + verification_id + "." + raw_body`. Receiver returns `2xx` and exact `Webhook-Verification: <challenge>`. Challenge is single use; a later verify replaces it.

### 7.5. Events

`POST /events` requires producer key and `Idempotency-Key` 16–128 visible ASCII chars:

```json
{
  "type":"media.processing.completed",
  "version":1,
  "occurred_at":"2026-08-27T12:00:00Z",
  "data":{"asset_id":"asset_123","job_id":"job_456","renditions":["1080p","720p"]}
}
```

Rules: request/canonical body <=256 KiB, JSON depth <=20, no NaN/Infinity, version 1–32767, occurred_at max 5 min future. Canonical JSON is UTF-8, compact separators, sorted keys. Fingerprint SHA-256 includes method, org/key identity and canonical bytes.

Response `202`: `{event_id,status:"accepted",delivery_count,created_at}` plus `Idempotency-Replayed`. Zero matching endpoints is valid.

Management:

- `GET /organizations/{org_id}/events` filters type/time/cursor;
- `GET /organizations/{org_id}/events/{event_id}` returns event and delivery summary.

### 7.6. Deliveries

- `GET /organizations/{org_id}/deliveries` filters endpoint/event/status/cursor.
- `GET /organizations/{org_id}/deliveries/{id}`.
- `GET /organizations/{org_id}/deliveries/{id}/attempts` ascending attempt number.
- `POST /organizations/{org_id}/deliveries/{id}/replay` owner/admin, terminal source and `Idempotency-Key` required → `202` new linked delivery.

Owner/admin may read non-expired bounded response preview; member sees metadata only. No stored arbitrary headers/cookies/auth.

### 7.7. Health

- `/health/live`: process only;
- `/health/ready`: DB and role-required broker dependencies, `503` if unavailable;
- `/metrics`: Prometheus, operational network only.

Development and test environments accept browser CORS preflight requests from loopback origins on
arbitrary local ports. Production disables that exception and uses exact HTTPS origins. Browser API
clients use Bearer tokens; cookie credentials are not part of the authentication contract.

## 8. Data model

All tables have server ID/created_at; time is `timestamptz`.

- `users`: normalized unique email, password hash, active.
- `refresh_tokens`: unique token hash, user/family, expiry/revoke/replacement.
- `organizations`: name/status.
- `memberships`: unique org/user, role, indexes both directions.
- `api_keys`: org, unique prefix, secret digest/digest-key version, scopes, revoke/last use.
- `webhook_endpoints`: org, name, canonical URL, status/enabled, verification hash/expiry, active delivery count constrained 0–3, deleted_at.
- `endpoint_secrets`: ciphertext/nonce/key version/active; one active partial unique.
- `endpoint_subscriptions`: endpoint/type unique.
- `events`: org/key/type/version/occurred_at/canonical `bytea`/data `jsonb`/idempotency/fingerprint; unique org/key/idempotency.
- `deliveries`: org/event/endpoint/status/attempt count/next attempt/lease/replay link/replay idempotency; original event/endpoint partial unique.
- `delivery_attempts`: org/delivery/number/start/end/outcome/status/latency/error/encrypted preview/retry decision; unique delivery/number.
- `outbox_messages`: topic/aggregate/payload/status/available/lease/attempts/published/error; pending index.
- `audit_events`: org, actor, action, resource, request ID, safe metadata.

Cross-org references are prevented. Repositories do not hidden-commit. Initial Alembic migration and empty DB upgrade→downgrade→upgrade test required.

## 9. State machines and process behavior

Endpoint: `pending_verification → active ↔ disabled → deleted`; URL change → pending; deleted terminal. Disable/delete prevents new deliveries and cancels pending/queued/retry; already in-flight attempt may finish.

Delivery:

```text
pending -> queued -> delivering -> succeeded
                         |-------> retry_scheduled -> queued
                         |-------> dead_lettered
pending|queued|retry_scheduled -> cancelled
```

Terminal: succeeded/dead_lettered/cancelled. Conditional updates enforce transitions.

### Outbox dispatcher

- Batch 100 pending due rows via `FOR UPDATE SKIP LOCKED`, lease 30 s.
- Publish persistent mandatory messages with publisher confirms.
- Mark published only after confirm; unknown/failed confirm leaves/retries row.
- Runs every <=500 ms, multiple instances safe; stale leases recover.

### Delivery worker

- Prefork concurrency 8, prefetch 1, late/manual ack.
- In a short transaction lock endpoint row, claim delivery with 30 s lease, increment `active_delivery_count` under cap 3 and create `started` attempt; commit before network I/O. Terminal/claimed duplicate produces no HTTP call.
- Perform DNS validation and one HTTP request with no open DB transaction.
- In a new short transaction finalize attempt/delivery, decrement counter, commit, then ack. Capacity deferral does not count as attempt; stale reconciler repairs lease/counter.
- Headers: `Webhook-Event-Id`, `Webhook-Delivery-Id`, `Webhook-Timestamp`, `Webhook-Attempt`, `Webhook-Signature`, content type/user agent.
- Connect timeout 3 s; total wall budget 10 s; redirects and client retries disabled; response preview max 4 KiB.

### Retry scheduler/reconciler

- Due rows claimed batch 100 with `SKIP LOCKED`; transition to queued + new outbox in one transaction.
- Retry results: network/timeouts/TLS, 408, 425, 429, 5xx. Success 2xx. Terminal: 3xx, other 4xx, unsafe destination/inactive endpoint.
- Delays after failure: 30 s, 2 min, 10 min, 1 h, 6 h plus full jitter 0–20%; total max six attempts.
- Valid Retry-After for 429/503 may increase delay capped 6 h.
- Stale delivering lease: open attempt becomes `unknown`, requeue if attempts remain else dead-letter.
- `dead_lettered` in DB is canonical DLQ; broker DLX is diagnostic only.

## 10. Limits/retention/overload

| Limit | Value |
| --- | ---: |
| Event body | 256 KiB |
| Endpoints / organization | 100 |
| Event types / endpoint | 50 |
| Non-terminal deliveries / organization | 10,000 |
| Concurrent calls / endpoint | 3 |
| Producer rate | 50 RPS, burst 100 per organization |
| Response preview | 4 KiB |
| Event/delivery/attempt metadata | 30 days |
| Response preview | 7 days |
| Audit | 90 days |

Projected backlog overflow rejects ingestion before insert with `429 backlog_limit_exceeded` and Retry-After. Login rate 5/min per IP+account; management 10 RPS/user. In-process rate limiting is accepted for the single-instance local stack; multiple replicas trigger distributed limiter design. Cleanup is bounded/idempotent and observable.

## 11. Security and observability

- BOLA tests for every organization resource; last-owner and scope checks.
- No secret/token/signature/raw payload/preview/full query string in log/metric/trace/error.
- Structured log correlation: request/event/delivery/attempt/task IDs.
- Metrics: HTTP RED, events accepted/replayed/rejected, delivery state/outcome, attempt duration/status/error, retries/DLQ, outbox/queue/retry lag, confirms/redeliveries/stale lease, SSRF/limit/auth rejects, worker in-flight/cap deferrals/cleanup failure.
- IDs/tenant/endpoint are never metric labels.
- Audit membership/key/endpoint/verification/replay/security actions.
- Runbooks: DB down, broker down, outbox lag, receiver failure storm, compromised secret.

Initial alert thresholds: readiness >2 min, oldest outbox >10 s, retry lag >30 s, DLQ >5%/15 min, worker saturation >90%/15 min.

## 12. Failure contract

- DB down: readiness false, no in-memory acceptance, dependent API `503`.
- Broker down: accepted event/outbox remains durable; dispatcher retries/alerts.
- Unknown confirm: republish allowed, consumer idempotent.
- Worker crash before request: redelivery/lease recovery; no loss.
- Crash after external side effect: duplicate possible with stable event ID and `unknown` evidence.
- Slow receiver: timeout and bounded retry; API remains independent.
- Unsafe DNS: no request, terminal security category/audit/metric.
- Scheduler/cleanup down: durable lag accumulates and resumes; observable.
- Missing crypto key/corrupt ciphertext: fail closed and dead-letter `secret_unavailable`.
- Invalid broker command: technical DLX; reconcile canonical DB state.

## 13. Initial SLO hypotheses

Record machine, OS, CPU/RAM, dataset and command before claiming results.

- event ingest p95 <300 ms at 50 RPS, <=64 KiB;
- management read p95 <300 ms at 25 RPS;
- outbox publish p95 <2 s while broker healthy;
- first attempt start p95 <5 s while receiver healthy;
- zero accepted metadata loss in tested crash scenarios;
- zero cross-tenant disclosure/prohibited network connection.

Unmeasured targets remain `pending`, never `passed`.

## 14. Required tests

- Unit: permissions, transitions, canonical JSON/fingerprint, retry/jitter, URL/IP, HMAC golden vector, crypto AAD, limits.
- API: auth rotation/reuse, one-time keys/revoke/scopes, BOLA, endpoint lifecycle, event/replay idempotency, pagination/errors/OpenAPI.
- PostgreSQL: constraints, transaction rollback, concurrent outbox/scheduler claims, leases, migrations.
- RabbitMQ: persistent mandatory confirm, confirm/DB crash window, manual ack/redelivery, poison command DLX.
- HTTP receiver: success, each retry/terminal class, Retry-After, slow/oversized response.
- Security: IPv4/IPv6 private/loopback/link-local/mapped, alternate IP notation, malformed/userinfo/Unicode URL, mixed A/AAAA, rebinding, redirect, TLS, redaction and production configuration fail-fast.
- E2E: register→key→endpoint→verify→event→success and failure→retry→DLQ→replay→success using local receiver only.
- Load/failure: stated targets, broker/worker restart, DB pool exhaustion, bounded memory/backlog and recovery.

## 15. Acceptance criteria

- `AC-001`: clean registration creates one org/owner; cross-tenant and last-owner negative tests pass.
- `AC-002`: API key/secret appear once and are never stored or listed plaintext; revocation works.
- `AC-003`: prohibited URL makes zero connection; endpoint activates only with exact live challenge.
- `AC-004`: event, exact matching original deliveries and outbox all commit or all roll back.
- `AC-005`: same idempotency request yields one event; changed input yields stable conflict.
- `AC-006`: confirm/DB uncertainty produces no lost outbox; duplicate is handled.
- `AC-007`: terminal duplicate command produces zero new HTTP calls.
- `AC-008`: receiver verifies HMAC against exact received body and defined headers.
- `AC-009`: every started HTTP call has immutable bounded encrypted attempt evidence.
- `AC-010`: retry matrix/schedule is exact, attempts <=6, exhaustion reaches dead-letter.
- `AC-011`: scheduler/dispatcher restarts and concurrent instances neither lose work nor create uncontrolled calls.
- `AC-012`: replay is linked/idempotent, keeps event ID and does not edit original.
- `AC-013`: backlog returns 429 and measured endpoint concurrency never exceeds 3.
- `AC-014`: retention cleanup is idempotent and audit/telemetry contain no forbidden values.
- `AC-015`: quality, typing, full tests, migration round trip and image build pass.
- `AC-016`: Compose local e2e verifies success and retry/DLQ/replay without public internet.
- `AC-017`: README contains Why, Use Cases, Who, Example, Guarantees and When Not to Use.
- `AC-018`: load report either proves initial targets or records deviations honestly.

## 16. Transition conditions

- Client compatibility: preserve the versioned API/OpenAPI contract used by the separate Web, iOS,
  and Android client; client implementation and release management remain outside this repository.
- Redis/distributed rate limiting: more than one API replica or measured bypass of local limiter.
- Separate service/deployment: independently scaled/owned/failing module with measured SLO/blast-radius need.
- Circuit breaker/auto-disable: one failing endpoint uses >20% worker capacity for 15 min.
- Range replay: >10 manual replay per incident or restoration backlog >1,000.
- Kafka/ordering: independent consumers, replayable log, per-key ordering or tuned RabbitMQ misses sustained target.
- Partitioning/archive: >100M event/attempt rows or retention/query SLO misses after index/query tuning.
- Private destination/custom CA/mTLS/port: separate egress/security ТЗ and threat review.
- Kubernetes: multiple deployables/replicas, self-healing, rolling updates, or autoscaling require measured operational need and clear ownership.

Every transition requires evidence, bottleneck analysis, simpler fixes, ADR, migration/rollout/rollback and before/after verification.

## 17. Implementation sequence

1. Foundation/tooling/settings/health/CI/Compose.
2. Identity, organizations, memberships, API keys.
3. Endpoint/subscription, encryption, SSRF and verification.
4. Event ingest/idempotency/transactional outbox.
5. Dispatcher/RabbitMQ/worker/HMAC/attempts.
6. Retry/reconciliation/DLQ/replay/cleanup/audit/metrics.
7. Local receiver/e2e/README/runbooks/load/security verification.

Each phase ends with relevant tests. No fake success endpoint, disabled gate, runtime mock or security bypass.

## 18. Definition of Done

- Starter documents preserved in `docs/` and root AGENTS remains active.
- Profile layout, dependencies, migrations, process roles and contracts are implemented.
- All FR behavior represented by tests and every AC passes.
- `uv lock --check`, Ruff format/lint, mypy, full pytest, migration round trip, Docker checks/build pass.
- Compose stack and documented acceptance flow reproduce success + retry/DLQ/replay locally.
- OpenAPI/error/task schemas match this document.
- Structured telemetry and runbooks cover failure paths without secrets/high-cardinality metric labels.
- README/architecture/delivery/security/limits/roadmap are understandable to an international reviewer.
- Verification reports distinguish measured facts from pending checks.
- No real credential, personal data, public webhook call, production change or known critical issue remains.

## 19. README wording requirements

README must state plainly:

- “This service decouples business transactions from unreliable customer endpoints.”
- “Delivery is at least once; consumers must deduplicate by `Webhook-Event-Id`.”
- “Ordering is not guaranteed in v0.1.”
- Use this product for managed webhook delivery/evidence/replay; do not use it as a Kafka replacement, workflow engine, synchronous RPC proxy or exactly-once ledger.

Do not claim production-ready, SOC 2/GDPR/ISO compliance, zero data loss under untested failures or achieved SLO without evidence.
