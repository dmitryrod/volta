# Volta

Панель опционов: снимки futures и ATM options (Bybit через unicex) с overlay Polymarket.

## Быстрый старт

```text
cd app-options
cp .env.example .env
# отредактируйте PANEL_PASSWORD и CYPHER_KEY
docker compose --env-file .env up --build -d
```

- Health: http://localhost:8081/health
- Панель: http://localhost:8081/login (логин из `.env`: `PANEL_LOGIN` / `PANEL_PASSWORD`)
- График: http://localhost:8081/chart

Prod URL (через edge Traefik): `PUBLIC_URL` в `.env`, по умолчанию https://volta.dmitryrod.ru

## Структура

| Путь | Назначение |
|------|------------|
| `app_options/` | Python-пакет (FastAPI, ingestor, auth) — имя пакета не менялось |
| `frontend/static/` | CSS/JS для панели |
| `nginx/` | Reverse proxy (dev: `nginx.conf`, prod: `nginx.prod.conf`) |
| `alembic/` | Миграции PostgreSQL |
| `docs/` | Документация |

## Документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — архитектура и docker
- [API.md](API.md) — REST контракты
- [FRONTEND.md](FRONTEND.md) — график и datafeed
- [CHANGELOG.md](CHANGELOG.md) — история изменений
- [troubleshooting.md](troubleshooting.md) — типовые проблемы

## Переменные окружения

См. `.env.example`. Обязательные для prod: `DATABASE_URL`, `PANEL_LOGIN`, `PANEL_PASSWORD`, `CYPHER_KEY`, `PUBLIC_URL`.

| Переменная | Назначение |
|------------|------------|
| `VOLTA_HTTP_PORT` | Host-порт nginx в dev (default 8081) |
| `VOLTA_POSTGRES_PORT` | Host-порт postgres с `--profile dev-tools` (default 5436) |
| `PUBLIC_URL` | Публичный URL панели (prod) |

## Вынос из monorepo

Volta живёт в каталоге `app-options/` репозитория money-pulso как **автономный стек** (свой compose, nginx, postgres, docs). Python-пакет остаётся `app_options`; UI-бренд — **Volta**.

Для отдельного репозитория:

1. Скопировать каталог `app-options/` целиком.
2. Обновить CI/CD и secrets (`.env`, не коммитить).
3. Prod: `docker compose -f docker-compose.prod.yaml up -d --build` на хосте с external network `proxy_network` (или переименовать в `apps_network` — см. ARCHITECTURE).
4. Edge Traefik: маршрут `Host(\`volta.dmitryrod.ru\`)` → `volta-nginx:80` (пример в troubleshooting).

Связи с money-pulso screener (`app/`) нет — только общий git monorepo на время миграции.

## Ограничения MVP

- Polymarket ingestor не реализован (схема + API + empty state в UI)
- SOL options на Bybit могут быть недоступны — collector пишет futures без call/put
- HTTPS в dev compose не публикуется; prod TLS на edge Traefik

## Traefik (reference only)

Пример dynamic/file config для prod — см. [troubleshooting.md](troubleshooting.md#prod-edge-traefik-volta).
