# Architecture

## Обзор

```
Browser -> nginx:80 (host :8081 dev) -> FastAPI:8000 -> PostgreSQL
                |-> /static/ (frontend)
IngestorOperator -> unicex (Bybit REST) -> SnapshotWriter -> PostgreSQL
```

UI-бренд: **Volta**. Python-пакет и cookie session: `volta` / `volta_session`.

## Компоненты

### api (FastAPI)

- `volta/__main__.py` — lifespan, SessionMiddleware, AuthMiddleware, title `Volta`
- Роуты: auth, chart/candles, meta, options (`routes_options.py`), polymarket
- Ingestor запускается в `lifespan` через `IngestorOperator`
- Порт **8000** только внутри docker network; на host не публикуется

### ingestor

| Модуль | Роль |
|--------|------|
| `operator.py` | Watchdog, restart stale collectors |
| `collectors/kline_ws_collector.py` | Bybit multiplex WS kline (3 symbols × 6 TF); REST backfill; closed bars → `futures_candles` |
| `collectors/options_snapshot.py` | Full nearest-expiry chain через `tickers("option")`, `ask_price`, purge expired |
| `writer.py` | UPSERT в Postgres |

Интервал: `SNAPSHOT_INTERVAL_SEC` (default 300). Watchdog перезапускает collector при `last_update_ts` старше `2 * interval`.

#### Options chain (ingestor)

1. `tickers(category="option", base_coin=BASE)` — все контракты Bybit.
2. Nearest expiry: earliest future expiry среди tickers; все strikes этой expiry пишутся в `instrument_snapshots`.
3. Цена: только `ask1Price` (без mid/mark fallback); строки без ask пропускаются.
4. `metric=ask_price`, `meta_json`: `{ option_type, strike, expiry, symbol }`.
5. Expiry канон: `_normalize_option_expiry` — дата контракта в **08:00 UTC**. Источники: `deliveryTime` / `expireDate` / symbol segment (`9SEP25`); symbol-only parse (00:00) нормализуется к 08:00, чтобы совпадать с API timestamp.
6. Reference pair для `panel_snapshots`: Hypothesis A defaults — min OTM call + max OTM put по futures spot; fallback — ближайший к spot strike.
7. Purge: после 08:00 UTC, не чаще 1 раза в UTC-сутки (`_last_purge_utc_date`); `DELETE` rows где `meta_json.expiry < now`.

#### Hypothesis A (OTM)

| Type | OTM when |
|------|----------|
| call | `strike > spot` |
| put | `strike <= spot` |

В `GET /api/options/chain` spot = `panel_snapshots.futures_price`; если panel нет — `spot=null`, все `otm=false`.

### database

- async SQLAlchemy + asyncpg
- Alembic migration `001` — четыре таблицы + seed `asset_config`
- `SnapshotRepository` — агрегация TF для chart API, `get_options_chain`, `aggregate_option_series`, `purge_expired_options`
- `futures_candles` — closed exchange OHLC (max 1000 per base+interval); migration `005`
- `CandleRepository` + `KlineHub` (in-memory forming bar, SSE fan-out)
- Chart futures: `get_futures_chart_candles` = DB closed + live merge; `has_more=false` (глубина ≤1000)
- `get_options_chain`: DISTINCT ON (symbol) latest ask; фильтр nearest expiry; calls/puts sorted by strike
- `get_chart_batch`: `options.series[]` через `aggregate_option_series(symbols[])`; без top-level call/put
- `polymarket_events` — каталог до 10 event URL per base; migration `004` + backfill из `asset_config`
- `aggregate_polymarket_series(..., event_slug)`: slug из query `pm_event_slug`; без slug — пустой `series[]`; фильтр `meta_json.event_slug`
- Polymarket ingest: loop всех активных events per base; `purge_expired_polymarket` после `event_end_date + PM_RETENTION_HOURS_AFTER_EXPIRY`
- Migration `003` — partial index `ix_instrument_snapshots_option_expiry` на `(base_asset, meta_json->>'expiry') WHERE market='option'`

### auth

- `SessionMiddleware` + `CYPHER_KEY`
- `AuthMiddleware` — `/chart`, `/api/*` требуют `session["authenticated"]`
- `/health`, `/login`, `/static/` — публичные

### nginx

- `location /static/` — alias на `frontend/static/`
- `location /` — proxy на `api:8000`, `proxy_http_version 1.1`, buffering off (SSE `/api/chart/stream`)
- Dev config: `nginx/nginx.conf` (`server_name _ localhost`)
- Prod config: `nginx/nginx.prod.conf` (`server_name volta.dmitryrod.ru`)

## Docker Compose

Project name: `volta`. Container names: `volta-postgres`, `volta-api`, `volta-nginx`.

### Port matrix (fixed)

| Endpoint | Dev (host) | Prod (host) | Internal |
|----------|------------|-------------|----------|
| nginx HTTP | `${VOLTA_HTTP_PORT:-8081}` → :80 | не публикуется | `volta-nginx:80` |
| api | — | — | `api:8000` |
| postgres | — (optional `--profile dev-tools`) | — | `postgres:5432` |
| postgres dev-tools | `${VOLTA_POSTGRES_PORT:-5436}` → :5432 | — | через `network_mode: service:postgres` |

Файлы:

| Файл | Назначение |
|------|------------|
| `docker-compose.yaml` | Local dev |
| `docker-compose.prod.yaml` | Prod: no host ports, `proxy_network` external |

Сборка `api`: multi-stage `Dockerfile` (builder ставит зависимости через `uv sync --locked --no-dev` по `uv.lock`, runtime копирует `.venv` и код, без `git`/`tests`). Старт контейнера: `alembic upgrade head`, затем `uvicorn` из `PATH` (`.venv/bin`). Миграции при каждом старте `api`. Повторный `--build` при неизменном `pyproject.toml` берёт слой deps из кэша.

### Prod networking

- `volta_internal` — postgres, api, nginx
- `proxy_network` (external) — только `volta-nginx`; edge Traefik маршрутизирует `volta.dmitryrod.ru` → `http://volta-nginx:80`
- **Без** Traefik labels на контейнерах Volta (конфиг на edge)

Альтернатива: если на хосте уже есть `apps_network`, замените `proxy_network` на `apps_network` в `docker-compose.prod.yaml` и в Traefik.

## unicex

Используется пакет с PyPI (`unicex>=0.16.6`): REST `futures_klines` + WS kline (один connection, 18 topics).

## Chart data paths (frontend)

```
[KlineWsCollector]
    REST backfill on start → futures_candles (closed only)
    WS 18 topics → KlineHub live + SSE broadcast
    confirm=true → upsert futures_candles + prune 1000

[loadChart]
    GET /api/chart/batch → futures, options, PM

[EventSource /api/chart/stream]
    live futures bar → futuresSeries.update (без сброса viewport)

[setInterval livePoll]
    tail batch → options/PM only (applyLiveUpdate)
```

| Аспект | Futures | Options / PM |
|--------|---------|----------------|
| History | `futures_candles` + live | `aggregate_*` из snapshots |
| Live | SSE stream | poll batch `from=` |
| Max depth | 1000 closed | как раньше |

Guards: `document.hidden`, `chartStore.loading`.

## Post-MVP

- Polymarket ingestor
- TimescaleDB hypertables
- TLS termination inside nginx (если без edge Traefik)
