# Troubleshooting

## Кнопки BTC/ETH/SOL или 1m/5m не переключают график

Симптом: клик по тикеру или таймфрейму не меняет `.active` и данные на `/chart`.

Причина: баг в `window.__voltaUi` — метод `setBase` вызывал сам себя вместо `changeChartBase` (shadowing); плюс устаревший `chart.js` в кэше (`expires 1h`). Toolbar layout: grid вместо flex overlay.

Шаги:

1. Hard refresh: Ctrl+Shift+R на `http://localhost:8081/chart`
2. DevTools → Network: `chart.js` должен грузиться с `?v=2` или свежим timestamp
3. После правок JS: `docker compose restart nginx api` в `app-options/`

Проверка: клик ETH → legend начинается с `ETH`, в Network batch `base=ETH`.

## Dev URL: localhost:8081, не :80

Симптом: `connection refused` на http://localhost/login или http://localhost/health.

Причина: в dev nginx публикуется на host-порт `${VOLTA_HTTP_PORT:-8081}`, не на 80.

Шаги: открыть http://localhost:8081/login и http://localhost:8081/health

Проверка:

```text
curl -s http://localhost:8081/health
```

## Prod edge Traefik (Volta)

Volta prod (`docker-compose.prod.yaml`) **не** публикует host ports и **не** использует Traefik labels на контейнерах. Edge Traefik на хосте проксирует HTTPS на `volta-nginx:80` в docker network `proxy_network` (или `apps_network` — см. ARCHITECTURE).

Предусловия:

1. External network существует: `docker network create proxy_network` (один раз)
2. `volta-nginx` подключён к этой сети (в prod compose уже настроено)
3. Traefik видит docker provider / file config на той же сети

Пример **file** dynamic config (reference only — путь зависит от вашего Traefik):

```yaml
http:
  routers:
    volta:
      rule: Host(`volta.dmitryrod.ru`)
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
      service: volta

  services:
    volta:
      loadBalancer:
        servers:
          - url: http://volta-nginx:80
```

Пример **docker labels** на **edge** Traefik container не нужен для Volta. Если используете docker provider, можно завести отдельный router через file provider, указывающий на hostname контейнера `volta-nginx`.

Проверка из сети proxy:

```text
docker run --rm --network proxy_network curlimages/curl:latest curl -s -o /dev/null -w "%{http_code}" http://volta-nginx/health
```

Ожидается `200`.

## Postgres на host (dev-tools)

Симптом: нужен прямой доступ к postgres с хоста (DBeaver, psql).

Причина: по умолчанию postgres не публикуется на host.

Шаги:

```text
docker compose --profile dev-tools up -d
```

Подключение: `localhost:${VOLTA_POSTGRES_PORT:-5436}`, user/db из `.env`.

## alembic: executable file not found in $PATH

Симптом: `docker compose exec api alembic upgrade head` падает с `exec: "alembic": executable file not found in $PATH`.

Причина: Alembic установлен в venv проекта (`uv sync`), не в глобальный PATH образа.

Шаги:

```text
docker compose exec api uv run alembic upgrade head
docker compose exec api uv run alembic current
```

Проверка: `current` показывает ревизию, например `005 (head)`.

Примечание: при `docker compose up` миграции уже выполняются в `command` сервиса `api` до старта uvicorn. Ручной `upgrade` нужен только если меняли `alembic/versions/` без пересоздания контейнера.

## postgres не стартует

Симптом: `api` в restart loop, `connection refused` к postgres.

Причина: healthcheck не прошёл или неверные `POSTGRES_*` в `.env`.

Шаги:

```text
docker compose logs postgres
docker compose ps
```

Проверка: `docker compose exec postgres pg_isready -U user -d options_data`

## 401 на /api/chart/batch

Причина: нет session cookie.

Шаги: войти через http://localhost:8081/login, убедиться что cookie `app_options_session` установлена.

Проверка:

```text
curl -c cookies.txt -b cookies.txt -X POST http://localhost:8081/login -d "username=admin&password=YOUR_PASSWORD"
curl -b cookies.txt "http://localhost:8081/api/meta/assets"
```

## nginx 502 Bad Gateway

Причина: контейнер `api` не слушает :8000 (crash при старте).

Шаги:

```text
docker compose logs api
```

Частые причины: миграция не прошла, неверный `DATABASE_URL`.

## Пустой график (нет свечей)

Причина: ingestor ещё не записал данные (интервал по умолчанию 300 сек).

Шаги:

```text
docker compose logs api
```

Подождать один цикл `SNAPSHOT_INTERVAL_SEC`, проверить:

```text
curl -b cookies.txt "http://localhost:8081/api/panel/latest?base=BTC"
```

## SOL без call/put

Причина: Bybit может не иметь options для SOL или API вернул ошибку.

Поведение: futures пишется, call/put null. См. логи `options-collector`.

## HTTPS / TLS

Dev: HTTP на `:8081` → nginx `:80` внутри compose.

Prod: TLS на edge Traefik (`websecure` + `letsencrypt`). Блок HTTPS в `nginx/nginx.prod.conf` закомментирован — включайте только если nginx сам терминирует TLS.

Self-signed для локального nginx TLS (редко):

```text
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout nginx/ssl/dummy.key -out nginx/ssl/dummy.crt -subj "/CN=localhost"
```

## CYPHER_KEY

При смене `CYPHER_KEY` все сессии сбрасываются. Используйте длинный случайный секрет в prod.
