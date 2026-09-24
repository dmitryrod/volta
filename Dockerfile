# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.MD alembic.ini uv.lock /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY volta /app/volta

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.13-slim

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml README.MD alembic.ini uv.lock /app/
COPY volta /app/volta
COPY alembic /app/alembic
COPY frontend /app/frontend
