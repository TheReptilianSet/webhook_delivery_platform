# Initial Implementation Verification — 2026-08-27

## Environment

- Windows host, Europe/Moscow timezone.
- Python 3.13 managed through `uv`; lock contains 98 resolved packages.
- Docker Desktop with Compose 5.4.0.
- Local PostgreSQL 17 and RabbitMQ 4 containers; callbacks were sent only to the exact Compose test
  receiver.

## Passed

| Area | Command or check | Result |
| --- | --- | --- |
| Frozen dependencies | `uv sync --all-groups --frozen` and `uv lock --check` | Passed |
| Formatting | `uv run ruff format --check .` | 112 files formatted |
| Lint | `uv run ruff check .` | Passed |
| Types | `uv run mypy src tests` | 94 source files, no issues |
| Full tests | `docker compose --profile test run --rm test pytest -q` | 70 passed in 21.03 s |
| Migrations | Alembic `upgrade head`, `downgrade base`, `upgrade head` on disposable `webhook_migration_test` | Passed |
| Compose validity | `docker compose config --quiet` | Passed |
| Images | `docker compose --profile test build` | Runtime, test, and receiver images built |
| Runtime health | `docker compose up -d --wait` | API, PostgreSQL, RabbitMQ, and receiver healthy; all process roles running |
| Local acceptance flow | `uv run python scripts/local_acceptance_flow.py` | Success, six-attempt DLQ path, and replay passed |
| HMAC receiver | Receiver records after the acceptance flow | Exact-body signatures reported `signature_valid=true` |
| Dependency audit | `uv run pip-audit --cache-dir .uv-cache/pip-audit` | No known vulnerabilities |

The full pytest command includes unit, API, security, real PostgreSQL, real RabbitMQ, and Compose e2e
tests. It emits one upstream FastAPI/Starlette `TestClient` deprecation warning; no test is skipped.
The dependency audit initially identified advisories in `cryptography 46.0.7` and `pytest 8.4.2`;
the lock was updated to `cryptography 50.0.1` and `pytest 9.1.1`, then all checks above were rerun.

## Failed or Not Run

- `docker build --check .` is unsupported by the installed legacy-compatible Docker CLI. The actual
  multi-stage image build passed.
- Docker Scout 1.24.0 was available but `docker scout cves` required Docker account authentication.
  No credentials were requested or used. CI contains pinned Trivy filesystem, secret, misconfiguration,
  and image scans; they remain unverified until CI runs.
- No load or prolonged fault-injection measurement was run. AC-018 performance targets therefore
  remain hypotheses; no throughput, p95 latency, SLO, restore, or capacity claim is made.
- CI itself was not executed remotely. No commit, push, deployment, package publication, or external
  service mutation was performed.

## Residual Operational Limits

- Rate limiting is process-local and is appropriate only for one API replica.
- DNS is revalidated before delivery, but deployment-level egress policy is still required to reduce
  DNS rebinding and network-policy risk.
- Delivery is at least once; a crash after receiver side effects and before durable finalization can
  produce a duplicate.
- Database and RabbitMQ durability, backup, restore, and multi-node behavior depend on the production
  operator and were not proven by this local acceptance flow.
