FROM python:3.13-slim

# Определяем рабочую директорию внутри контейнера
WORKDIR /app

# Устанавливаем git и системные зависимости
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Устанавливаем uv
RUN pip install --no-cache-dir uv

# Настраиваем режим работы uv
ENV UV_LINK_MODE=copy

# Копируем зависимости проекта (pyproject.toml лежит в папке app на хосте)
COPY app/pyproject.toml /app/pyproject.toml

# Копируем конфиг alembic
COPY app/alembic.ini /app/alembic.ini

# Устанавливаем зависимости
RUN uv sync

# Копируем исходники приложения (пакет app) внутрь контейнера
COPY app /app/app

# Подменяем websocket в установленном unicex на пропатченный (403 backoff + очистка очереди)
RUN cp /app/app/unicex/_base/websocket.py /app/.venv/lib/python3.13/site-packages/unicex/_base/websocket.py