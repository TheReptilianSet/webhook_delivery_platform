# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.24 AS uv

FROM python:3.13-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-group security --no-editable

FROM builder AS test
COPY tests ./tests
COPY scripts ./scripts
RUN uv sync --all-groups --frozen --no-editable

FROM python:3.13-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && groupadd --system webhook \
    && useradd --system --gid webhook --home-dir /app webhook
WORKDIR /app
COPY --from=builder --chown=webhook:webhook /app/.venv /app/.venv
COPY --chown=webhook:webhook src ./src
COPY --chown=webhook:webhook alembic ./alembic
COPY --chown=webhook:webhook alembic.ini README.md ./
USER webhook
EXPOSE 8000
CMD ["uvicorn", "webhook_platform.main:app", "--host", "0.0.0.0", "--port", "8000"]
