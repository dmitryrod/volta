FROM python:3.13-slim

WORKDIR /app

RUN apt-get update
RUN apt-get install -y --no-install-recommends git
RUN rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

ENV UV_LINK_MODE=copy

COPY pyproject.toml /app/pyproject.toml
COPY README.MD /app/README.MD
COPY alembic.ini /app/alembic.ini

RUN uv sync

COPY app_options /app/app_options
COPY alembic /app/alembic
COPY frontend /app/frontend
COPY tests /app/tests
