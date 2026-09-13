# API

Все `/api/*` (кроме косвенно защищённых через middleware) требуют активной сессии. Без сессии: `401 {"detail":"Unauthorized"}`.

## Public

### GET /health

```json
{"status": "ok", "environment": "development"}
```

## Auth

### GET /login

HTML форма входа.

### POST /login

Form fields: `username`, `password`. Успех: redirect `/chart`. Ошибка: 401 + форма с сообщением.

### POST /logout

Сброс сессии, redirect `/login`.

## Chart

### GET /chart

HTML панель (auth required).

### GET /api/meta/assets

```json
[
  {"base": "BTC", "futures_symbol": "BTCUSDT", "pm_event_slug": null, "pm_event_url": null}
]
```

### GET /api/options/chain

Query: `base` (required, BTC|ETH|SOL)

Последний ask per symbol (`metric=ask_price`) для nearest expiry chain.

| Field | Source / rule |
|-------|----------------|
| `spot` | `panel_snapshots.futures_price` (latest); `null` если panel нет |
| `expiry` | ISO 8601, канон **08:00 UTC** |
| `expiry_label` | `{day} {MON} {yy}`, напр. `9 SEP 25` |
| `otm` | Hypothesis A при `spot != null`; иначе **всегда `false`** |

Hypothesis A:

- call OTM: `strike > spot`
- put OTM: `strike <= spot`

Calls и puts отсортированы по `strike` ascending.

Response `200`:

```json
{
  "base": "ETH",
  "expiry": "2025-09-09T08:00:00+00:00",
  "expiry_label": "9 SEP 25",
  "spot": 2513.45,
  "calls": [
    {
      "symbol": "ETH-9SEP25-2520-C-USDT",
      "strike": 2520,
      "ask_price": 12.5,
      "otm": true
    }
  ],
  "puts": []
}
```

Empty chain: `calls: []`, `puts: []`, `expiry: null`, `expiry_label: null`. `spot` может быть non-null из panel даже при пустом chain.

Ingest `meta_json` (в `instrument_snapshots`, не в chain response): `option_type`, `strike`, `expiry`, `symbol`. Ask — только `ask1Price`.

### GET /api/chart/batch

Query:

| Param | Required | Description |
|-------|----------|-------------|
| base | yes | BTC, ETH, SOL |
| interval | no | 1m, 5m, 15m, 1h, 4h, 1d (default 5m) |
| from | no | unix sec; inclusive lower bound для candles/points (`time >= from`) |
| to | no | unix sec |
| limit | no | 1-5000, default 500 |
| symbols | no | comma-separated Bybit option symbols для `options.series` |
| pm_event_slug | no | slug выбранного Polymarket event для `polymarket.series` |

**Futures candles:** биржевые OHLC из `futures_candles` (closed, max 1000) + forming bar из `KlineHub`. `has_more` всегда `false` для futures.

**Семантика `from`:** фильтр по timestamp бара/точки. Full load (`loadChart`) обычно без `from`. Live tail-fetch (options/PM): overlap на 1 bucket.

### GET /api/chart/stream

SSE live updates для futures candlestick (auth required).

Query: `base` (required), `interval` (default `5m`).

Events (`text/event-stream`):

```json
{"type": "kline", "base": "ETH", "interval": "5m", "candle": {"time": 1725800400, "open": 2500, "high": 2520, "low": 2490, "close": 2513}, "confirmed": false}
```

- `confirmed: false` — forming bar update
- `confirmed: true` — свеча закрыта на бирже (также persisted в `futures_candles`)

Пример live tail-fetch options/PM (клиент `pollLiveUpdate`):

```
GET /api/chart/batch?base=ETH&interval=5m&from=1725800100&limit=20&symbols=ETH-9SEP25-2520-C-USDT
```

- `from` = `newestTime - bucketSec` (для 5m: `newestTime - 300`)
- `limit` = 20 (`LIVE_UPDATE_LIMIT`)
- Ответ — тот же shape; клиент мержит через `mergeByTime`, без сброса viewport

Response:

```json
{
  "base": "ETH",
  "interval": "5m",
  "futures": {"candles": [{"time": 1725800400, "open": 2500, "high": 2520, "low": 2490, "close": 2513}], "has_more": false},
  "options": {
    "expiry": "2025-09-09T08:00:00+00:00",
    "series": [
      {
        "symbol": "ETH-9SEP25-2520-C-USDT",
        "strike": 2520,
        "option_type": "call",
        "label": "$2,520 C",
        "points": [{"time": 1725800400, "value": 12.5}]
      }
    ],
    "has_more": false
  },
  "polymarket": {"series": [], "event_slug": null, "event_url": null, "has_more": false}
}
```

**Removed:** top-level `call`, `put` (breaking change).

Без `symbols` — `options.series: []`. С `symbols` — time series ask_price per symbol; `label` вида `$2,520 C`.

### GET /api/candles

Query: `base`, `series` (futures|call|put|option), `interval`, `from`, `to`, `limit`.

- `series=option` требует `symbol` (Bybit option symbol).
- `series=call|put` — deprecated, читает `panel_snapshots`.

Response для `option`:

```json
{
  "series": "option",
  "symbol": "ETH-9SEP25-2520-C-USDT",
  "interval": "5m",
  "points": [{"time": 1725800400, "value": 12.5}],
  "has_more": false
}
```

### GET /api/probability

Query: `base`, `from`, `to`, `limit`. Returns `{base, points: [{time, value}]}`.

### GET /api/panel/latest

Query: `base`. Последний `panel_snapshots` + polymarket snapshot. `options_expiry` берётся из `get_options_chain` (nearest expiry chain), не из panel row.

Если panel нет: `{ "base": "...", "panel": null, "polymarket": null }`.

```json
{
  "base": "ETH",
  "panel": {
    "ts": 1725800400,
    "futures_symbol": "ETHUSDT",
    "futures_price": 2513.45,
    "call_price": 12.5,
    "put_price": 14.3,
    "call_symbol": "ETH-9SEP25-2520-C-USDT",
    "put_symbol": "ETH-9SEP25-2510-P-USDT",
    "options_expiry": "2025-09-09T08:00:00+00:00"
  },
  "polymarket": null
}
```

`call_*` / `put_*` — reference ATM pair (Hypothesis A defaults, ask prices).

## Polymarket

Каталог до `PM_MAX_EVENTS_PER_BASE` (default 10) событий per base в таблице `polymarket_events`. Ingest пишет snapshots по всем активным событиям; на графике — одно выбранное (`pm_event_slug`).

### GET /api/polymarket/events

Query: `base`.

```json
{
  "base": "ETH",
  "events": [
    {
      "event_slug": "ethereum-above-on-september-9-2026",
      "event_url": "https://polymarket.com/event/...",
      "event_title": "...",
      "event_end_date": "2026-09-09T23:59:59Z"
    }
  ],
  "max_events": 10
}
```

Только события в окне `event_end_date + PM_RETENTION_HOURS_AFTER_EXPIRY` (или без `event_end_date`).

### POST /api/polymarket/events/import

Body: `{ "base": "ETH", "urls_text": "https://...\nhttps://..." }` — одна URL на строку, dedupe по slug, merge add/update (без replace-all). 400 при превышении `max_events` или невалидном URL.

### GET/POST /api/polymarket/config (deprecated)

Read-only compat: возвращает первое событие каталога. POST проксирует single-URL import.

## Errors

| Code | When |
|------|------|
| 400 | invalid base, interval, series, missing symbol for option |
| 401 | no session |
