---
type: bootstrap-profile
status: active
scope: webhook-delivery-platform
applies_when: creating_or_maintaining_this_project
last_reviewed: 2026-08-28
---

# Webhook Delivery Platform Bootstrap Profile

## 1. Назначение

Документ задаёт один воспроизводимый layout, stack, process contract, containers, CI и commands. Product behavior и acceptance criteria задаёт `PROJECT_SPECIFICATION.md`, который имеет приоритет.

## 2. Стартовый стек

| Area | Decision |
| --- | --- |
| Python | 3.13 |
| Dependencies/build | `uv`, committed `uv.lock`, Hatchling |
| API | FastAPI, Uvicorn, Pydantic 2, pydantic-settings |
| Persistence | PostgreSQL, SQLAlchemy 2 async, asyncpg, Alembic |
| Commands | Celery + RabbitMQ |
| Outbound HTTP | HTTPX |
| Crypto/auth | Python HMAC, cryptography AES-GCM, pwdlib Argon2, PyJWT |
| Metrics | prometheus-client |
| Tests | pytest, pytest-asyncio, HTTPX, testcontainers |
| Quality | Ruff, mypy |
| Containers/CI | Docker, Docker Compose, GitHub Actions |

Точные library versions фиксирует lockfile. Не использовать floating dependency installation в CI.

## 3. Repository layout

```text
.
├── README.md
├── LICENSE
├── CHANGELOG.md
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .env.example
├── .gitignore
├── .github/workflows/ci.yml
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── docs/
│   ├── COMMUNITY.md
│   ├── bootstrap/PROJECT_BOOTSTRAP_PROFILE.md
│   ├── specifications/PROJECT_SPECIFICATION.md
│   ├── decisions/
│   ├── runbooks/
│   └── verification/
├── scripts/
│   └── local_acceptance_flow.py
├── tools/
│   └── test_receiver/
│       ├── Dockerfile
│       └── app.py
├── src/webhook_platform/
│   ├── __init__.py
│   ├── main.py
│   ├── container.py
│   ├── worker.py
│   ├── outbox_dispatcher.py
│   ├── scheduler.py
│   ├── config/
│   │   └── settings.py
│   ├── shared/
│   │   ├── domain/errors.py
│   │   ├── application/ports.py
│   │   └── infrastructure/
│   │       ├── database.py
│   │       ├── logging.py
│   │       ├── metrics.py
│   │       └── request_context.py
│   ├── identity/
│   │   ├── api/{dependencies.py,router.py,schemas.py}
│   │   ├── application/{dto.py,ports.py,use_cases.py}
│   │   ├── domain/{entities.py,errors.py,value_objects.py}
│   │   └── infrastructure/{models.py,repository.py,password_hasher.py,token_service.py}
│   ├── organizations/
│   │   ├── api/{dependencies.py,router.py,schemas.py}
│   │   ├── application/{dto.py,ports.py,use_cases.py}
│   │   ├── domain/{entities.py,enums.py,errors.py}
│   │   └── infrastructure/{models.py,repository.py,api_key_service.py}
│   ├── endpoints/
│   │   ├── api/{dependencies.py,router.py,schemas.py}
│   │   ├── application/{dto.py,ports.py,use_cases.py}
│   │   ├── domain/{entities.py,enums.py,errors.py,transitions.py}
│   │   └── infrastructure/{models.py,repository.py,crypto.py,safe_http.py,dns.py}
│   ├── events/
│   │   ├── api/{dependencies.py,router.py,schemas.py}
│   │   ├── application/{dto.py,ports.py,use_cases.py}
│   │   ├── domain/{entities.py,errors.py,canonical_json.py}
│   │   └── infrastructure/{models.py,repository.py}
│   ├── deliveries/
│   │   ├── api/{dependencies.py,router.py,schemas.py}
│   │   ├── application/{dto.py,ports.py,use_cases.py}
│   │   ├── domain/{entities.py,enums.py,errors.py,retry.py,transitions.py}
│   │   └── infrastructure/{models.py,repository.py,celery_tasks.py,signing.py}
│   ├── outbox/
│   │   ├── application/{ports.py,use_cases.py}
│   │   └── infrastructure/{models.py,publisher.py,repository.py}
│   └── maintenance/
│       └── application/{cleanup.py,reconcile.py}
└── tests/
    ├── conftest.py
    ├── fixtures/
    ├── unit/{identity,organizations,endpoints,events,deliveries}/
    ├── api/
    ├── integration/
    ├── security/
    └── e2e/
```

Каждый package directory получает `__init__.py`, опущенный в сокращённом дереве. Не создавать `services/`, `utils.py`, `helpers.py`, generic base repository/service. Общий код переносится в `shared` только после второго реального consumer.

## 4. Package/dependency contract

`pyproject.toml`:

- project `webhook-delivery-platform`, version `0.1.0`, Python `>=3.13,<3.14`;
- Hatchling src layout;
- dependency groups `dev` and `security`;
- Ruff target `py313`, line length 100, formatter + lint rules `E,F,I,UP,B,SIM,ASYNC,DTZ,RUF`; justified per-file ignores only;
- mypy Python 3.13, `strict = true` for `src`, explicit test relaxations only;
- pytest `asyncio_mode = auto`, markers `unit`, `api`, `integration`, `security`, `e2e`, `load`;
- coverage branch enabled, report diagnostic; no arbitrary 100% target.

Runtime dependencies: FastAPI, Uvicorn standard, Pydantic/pydantic-settings, SQLAlchemy async, asyncpg, Alembic, Celery with RabbitMQ client, HTTPX, cryptography, pwdlib Argon2, PyJWT, email-validator, prometheus-client, structlog.

Development: pytest, pytest-asyncio, pytest-cov, testcontainers PostgreSQL/RabbitMQ, Ruff, mypy, httpx, pip-audit and types packages only when required. No Redis/object storage/media dependencies.

## 5. Architecture and composition

```text
api/process wrapper -> application use case -> domain
infrastructure adapter ---------------------> ports/domain
```

- Domain is framework-free.
- Application owns transaction/use-case boundary and uses protocols/ports.
- Infrastructure maps SQLAlchemy/HTTPX/Celery/crypto exceptions to application errors.
- `container.py` is explicit composition root; no service locator/global mutable session.
- `main.py:create_app()` creates FastAPI, middleware, routers and lifespan resources.
- `worker.py`, `outbox_dispatcher.py`, `scheduler.py` are separate entrypoints using the same use cases.
- One `AsyncSession` per request/use-case; no sharing across concurrent tasks.
- Repository flushes when needed and never silently commits.
- UTC aware time only; due/lease decisions use PostgreSQL `now()`.

## 6. Settings contract

Prefix: `WEBHOOK_PLATFORM_`; nested delimiter `__`. `.env.example` contains synthetic development values only.

Required groups:

- environment, log level, public base URL, API bind/port;
- PostgreSQL DSN and bounded pool size/overflow/timeouts;
- RabbitMQ DSN, queue/exchange/DLX names, publisher confirm timeout;
- JWT signing secret, API-key digest pepper/key version, issuer/audience, access/refresh TTL;
- AES-GCM master key and integer key version;
- event size/rate/backlog limits;
- worker concurrency/prefetch, leases, outbox/retry batches;
- HTTP connect/pool/total timeouts, response preview cap;
- retry delays/max attempts/jitter;
- metadata/preview/audit retention;
- exact development receiver allowlist.

Production validation fails when secrets are defaults/too short, debug is enabled, HTTP/private destination exception is enabled, test API-key prefix is accepted, wildcard CORS is used with credentials or broker/DB TLS policy is inconsistent with deployment config.

Settings are immutable after startup and secrets use redacted representations.

## 7. Database/migration contract

- Runtime/integration tests use PostgreSQL; SQLite substitute forbidden.
- SQLAlchemy naming convention gives deterministic constraints/indexes.
- Enums, partial unique indexes, bytea/jsonb and `FOR UPDATE SKIP LOCKED` are explicit repository behavior.
- Initial Alembic migration creates all specification tables/constraints/indexes.
- CI creates empty DB, runs `upgrade head`, application DB smoke, `downgrade base`, `upgrade head`.
- Application startup does not call `metadata.create_all`.
- Released revision is immutable. Later changes use expand/backfill/switch/contract.

## 8. Broker/process contract

RabbitMQ topology is declared idempotently:

- durable direct exchange `webhook.delivery`;
- durable queue `webhook.delivery.v1` with routing key `delivery.execute.v1`;
- durable DLX/queue `webhook.delivery.dlx` / `webhook.delivery.dead.v1`;
- persistent messages, mandatory publish and publisher confirms;
- message body `{schema_version:1, delivery_id, correlation_id}`.

Celery delivery worker:

- prefork concurrency 8 local default;
- late/manual acknowledgement, `worker_prefetch_multiplier=1`, reject on worker loss;
- broker message ack only after durable DB outcome;
- no Celery result backend as product state;
- HTTP client performs no automatic retry.

Outbox dispatcher and retry scheduler are long-running roles with graceful shutdown, bounded batches and leases. They may run multiple instances; `SKIP LOCKED` prevents claim contention. Logical delivery DLQ remains PostgreSQL state; broker DLQ is diagnostic.

## 9. Outbound security contract

- Production URL: HTTPS port 443, no userinfo/fragment, all A/AAAA public.
- Revalidate DNS directly before each connect; reject if any address unsafe.
- Disable redirects; `3xx` is terminal.
- Explicit HTTPX connect/read/write/pool budgets within 10-second wall limit.
- Stream response and retain at most 4 KiB encrypted preview; discard forbidden headers.
- AES-256-GCM for webhook secret/preview with unique nonce, key version and resource ID AAD.
- HMAC-SHA256 over exact canonical bytes and specified fields.
- Test receiver exception is exact host/port, development/test only. CI has no public egress dependency.

Implement network policy as an application port so DNS resolver/connector can be deterministically tested. Do not claim TOCTOU-proof network isolation without deployment egress controls; local MVP must still perform validation at registration and attempt time.

## 10. API/runtime contract

- API prefix `/api/v1`; routers by module; Pydantic request/response schemas separate from ORM.
- Consistent error envelope/codes and `X-Request-Id`; user input never becomes raw exception response.
- Cursor/keyset pagination; no unbounded lists.
- Authn and organization resource authorization are separate dependencies/use cases.
- Request body limit enforced before JSON parsing when possible and after decoding by canonical-size check.
- Local CORS permits loopback origins on arbitrary ports for Bearer-token clients; production
  disables this exception and accepts only configured HTTPS origins.
- Lifespan creates/disposes DB/HTTP/broker resources; readiness is dependency-aware, liveness is not.
- Prometheus route is operational/private by deployment; no high-cardinality IDs as labels.

## 11. Docker/Compose contract

Dockerfile: multi-stage Python 3.13 slim, non-root runtime, frozen lock sync, source installed, healthcheck-capable, one immutable image for every process role. No compiler/cache/test tools in runtime stage. Pin base digest before release; local development may start from a versioned tag.

Compose services:

- `postgres` with healthcheck and named volume;
- `rabbitmq` with healthcheck and named volume;
- `migrate` one-shot after healthy PostgreSQL;
- `api` after successful migrate and broker readiness;
- `outbox-dispatcher`;
- `retry-scheduler`;
- `delivery-worker`;
- `test-receiver` exact local-only destination.

Local ports: API `8000`, PostgreSQL `5432`, RabbitMQ `5672/15672`, receiver `8080`. Production-like profile must not publish DB/broker management ports.

Use `init: true`, graceful stop, explicit resource limits/reservations where Compose supports them and no privileged/root/container socket mounts. Do not include `down -v` in normal commands.

## 12. Test strategy

- Unit: pure transitions, permissions, canonicalization, HMAC, retry, IP classification, limit decisions.
- API: auth, scopes, BOLA, idempotency, validation, pagination, stable errors/OpenAPI.
- Integration: real PostgreSQL/RabbitMQ and local receiver, migrations, outbox confirms, ack/redelivery, concurrency/leases.
- Security: IPv4/IPv6 SSRF corpus, DNS rebinding simulation, redirects, crypto/log redaction and production config guard.
- E2E: complete success and retry→DLQ→replay flows from Compose.
- Load/failure: separate local command; record hardware/dataset/results in `docs/verification/`, never invent them.

Tests use deterministic injected clock/random/DNS where needed. Integration tests must also cover actual socket resolution/HTTP adapter on isolated test network. No test calls real external domains.

## 13. Canonical commands

```bash
uv sync --all-groups --frozen
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m unit
uv run pytest -m "api or integration or security"
uv run pytest -m e2e
uv run pytest
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
docker compose config --quiet
docker build --check .
docker compose build
docker compose up -d --wait
uv run python scripts/local_acceptance_flow.py
docker compose down
```

If installed tool does not support a command on the locked version, replace it with the version-supported equivalent and document the change; do not silently skip the check.

## 14. CI contract

Pull-request workflow, least permissions, concurrency cancellation, pinned Actions by commit SHA:

1. quality: frozen sync, lock check, Ruff, mypy;
2. tests: PostgreSQL/RabbitMQ services, migrations, full pytest including security;
3. build: Docker build after quality/tests, no push;
4. security: dependency audit, secret scan and container/filesystem scan with documented severity policy.

CI uses synthetic credentials, local receiver and no production/public webhook. Artifact provenance/build publishing belongs to a later release workflow.

## 15. README/documentation contract

README sections in English:

1. Why This Project Exists;
2. Use Cases: transcoding, AI generation, moderation, transcription, previews, and media transfers;
3. Who It Is For;
4. Example Scenario;
5. Delivery Guarantees: at-least-once, duplicates, no ordering;
6. When Not to Use It;
7. Architecture and transaction/outbox sequence;
8. Stack and key trade-offs;
9. Quick Start prerequisites and canonical commands;
10. local API acceptance walkthrough including signature verification;
11. Security/SSRF model;
12. Retry/DLQ/replay and failure model;
13. Limits/retention/configuration;
14. Testing/CI/verification evidence;
15. Roadmap/transition triggers;
16. license and security reporting.

Add Mermaid context/sequence diagrams, `docs/runbooks/` for DB, broker, outbox lag, receiver failure storm and secret compromise, and `docs/verification/README.md` distinguishing pending from measured evidence.

## 16. Implementation sequence

### Phase 1 — Foundation

Foundation, lockfile, settings validation, app factory, DB base, error envelope, request IDs, health/metrics, Docker/Compose, and CI. No product endpoint stub success.

### Phase 2 — Identity and tenancy

Users/auth/refresh, organizations/memberships/roles, API keys, migrations, BOLA and concurrency tests.

### Phase 3 — Safe endpoints

Endpoint/subscription lifecycle, AES-GCM secret adapter, URL/DNS policy, verification receiver contract and adversarial SSRF tests.

### Phase 4 — Event control plane

Canonical JSON, ingestion/scopes/limits/idempotency, transactional event/delivery/outbox creation and management reads.

### Phase 5 — Delivery data plane

Outbox dispatcher/confirms, Celery topology, worker claim/lease, HMAC POST, attempt evidence and duplicate command handling.

### Phase 6 — Reliability operations

Retry scheduler/jitter, stale reconciliation, DLQ, replay, cleanup, audit, metrics and runbooks.

### Phase 7 — Operational readiness

Local receiver and acceptance flow, complete e2e/load/failure checks, README/diagrams, security scans, and verification report.

## 17. Release readiness gate

- all three starter files preserved in docs and root AGENTS active;
- exact layout/tooling/settings/process roles exist;
- migrations and public/task contracts match specification;
- canonical quality/test/build/Compose checks pass or exact external blocker is reported;
- acceptance flow sends only to the local receiver and verifies success + retry/DLQ/replay;
- README makes business use and delivery trade-offs understandable to an international reviewer;
- no fake evidence, committed secret, critical security failure or unapproved infrastructure.

## 18. Primary references

- [Python 3.13 documentation](https://docs.python.org/3.13/)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [PostgreSQL SELECT locking](https://www.postgresql.org/docs/current/sql-select.html)
- [RabbitMQ confirms and acknowledgements](https://www.rabbitmq.com/docs/confirms)
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
