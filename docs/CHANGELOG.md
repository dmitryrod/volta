# Changelog

## Unreleased

### Changed

- Docker image: multi-stage Dockerfile (builder `uv sync --locked --no-dev`, runtime только `.venv` + код). Убраны `git` и `tests` из образа. Compose `api` стартует `alembic`/`uvicorn` из `.venv/bin`, без `uv run`. В репо добавлен `uv.lock`
- `.dockerignore`: исключены `.git`, `.venv`, `tests`, `docs`, `.env`

### Changed

- Rebrand UI: **Volta** (toolbar, login, page titles, FastAPI title); Python package остаётся `app_options`
- Docker dev: project `volta`, nginx host port `${VOLTA_HTTP_PORT:-8081}`, postgres host port только с `--profile dev-tools` (`${VOLTA_POSTGRES_PORT:-5436}`)
- Docker prod: `docker-compose.prod.yaml` — без host ports, nginx на `proxy_network`, `nginx.prod.conf` для `volta.dmitryrod.ru`
- `.env.example`: `VOLTA_HTTP_PORT`, `VOLTA_POSTGRES_PORT`, `PUBLIC_URL`

### Added

- Futures chart: биржевые klines Bybit — REST backfill (до 1000 closed баров на base+TF), один WS (18 топиков: 3 символа × 6 TF), таблица `futures_candles`, SSE `GET /api/chart/stream` для live текущей свечи

### Fixed
- Chart left price scale restore (F5 / base / TF): `capturePriceScaleState` читает in-memory pin до `visible:false`; sanitize/restore left plausibility по mid сохранённого range (не last OTM option); `mergeCapturedPriceScales` сохраняет left pin при poisoned capture; `hasRestorableLayout` учитывает left-only pin; restore price scales даже после fallback `fitContent`; `applyToggles` на каждой restore-попытке
- Chart layout persistence (holistic): `readChartLayout`/`sanitize` после `setData` (plausibility с live option/futures ref); sanitize не валидирует range по собственному poisoned mid; right-axis hit-test симметричен left; `applyUserInteractedFlagsFromLayout` после restore; сброс `*ScaleUserInteracted` при `loadChart(reset)`
- Chart layout persistence (ticker switch): `flushSaveLayout` до смены base + `layoutSwitchInProgress` блокирует debounced save между сменой `chartStore.base` и `loadChart`, пока chart ещё показывает предыдущий тикер (регрессия от async `loadPmEventsForBase`)
- Chart layout persistence (TF switch): `changeChartInterval` симметричен `changeChartBase` — `cancelPendingLayoutSave`, `flushSaveLayout(prev)` до смены `chartStore.interval`, `layoutSwitchInProgress` на время `loadChart`; раньше interval менялся до flush и debounced save мог перезаписать layout без left pin
- Chart left price scale (options): Y-zoom left axis снова сохраняется в sessionStorage и restore после F5 / смены base / TF; plausibility vs option premium ref (не futures spot); initial pin при `autoScale:true` + `leftScaleUserInteracted`; wheel над left axis помечает left interaction
- Chart right price scale (futures): после Y-zoom/restore больше не показывает billions/e+45; plausibility guard vs futures ref + `rightScaleUserInteracted` (симметрия left fix)
- Chart left price scale (options): после Y-zoom правой шкалы и reload layout больше не показывает ±10^9; plausibility guard + не pin left на global wheel/pointer без drag left axis
- Chart toolbar: BTC/ETH/SOL и TF tabs снова переключают график (`onclick` binding, grid layout toolbar вместо flex overlay)
- Polymarket per-base isolation: PM URL и overlay строго per base (BTC/ETH/SOL); backend фильтрует snapshots по `event_slug`; frontend `clearPmOverlay()` при смене base и при отсутствии config
- Chart layout persistence: restore до/после `setData` без перезаписи sessionStorage (layoutRestoring + cancel debounced save); logical range restore приоритетнее time range; retry/verify после rAF
- Chart Y-zoom persistence: `syncPinnedPriceScalesFromViewport` при manual drag/zoom; `pagehide` flush без event-as-base; SSE/poll старт после restore; `refreshPinnedPriceScalesIfNeeded` после live bar update
- Chart layout persistence (regression): `persistChartLayout` + merge на debounced save (не затирать Y-zoom); rAF x2 sync после wheel/pointer; sanitize poisoned `priceScales` при read; `visibilitychange` flush + guarded SSE resume; `applyToggles` до restore retry; flush перед options/PM reload

### Added

- Polymarket events catalog per base: таблица `polymarket_events`, API `GET/POST /api/polymarket/events`, bulk import (textarea), radio selection на графике, `pm_event_slug` на `/api/chart/batch`, multi-event ingest + purge после expiry (`PM_RETENTION_HOURS_AFTER_EXPIRY`, default 24h)
- Chart layout persistence: pan/zoom и price scales в `sessionStorage` (`chart_layout_<BASE>_<INTERVAL>`, JSON v1); debounce save 400 ms; restore после full batch load; first visit — `fitContent`
- Chart live refresh: futures через SSE `/api/chart/stream`; options/PM — tail polling через `GET /api/chart/batch?from=` + `applyLiveUpdate`; пауза при hidden tab и loading
- Multi-strike options chain: ingestor пишет все strikes nearest expiry с `metric=ask_price` и `meta_json` (strike, expiry, option_type)
- API `GET /api/options/chain` — текущий chain с OTM-флагами (Hypothesis A)
- Chart batch: `options.series[]` + query param `symbols`; `/api/candles?series=option&symbol=...`
- Purge истёкших option rows после 08:00 UTC (idempotent, max 1/day); migration `003` partial index на expiry
- UI: Options dropdown (Call | Put columns), `optionSeriesMap`, sessionStorage selection, expiry rollover
- `panel/latest`: поле `options_expiry`
- Polymarket: `event_end_date` в `/api/polymarket/config`; countdown таймер экспирации слева от URL в chart UI

### Changed (earlier unreleased)

- **Breaking:** Polymarket chart UI: single URL form заменён на dropdown catalog (import + radio); PM overlay требует `pm_event_slug` в batch request
- **Breaking:** `/api/chart/batch` — удалены top-level `call`/`put`; вместо них `options.series[]`
- Ingestor panel reference pair: ask prices по Hypothesis A (call strike > spot, put strike <= spot)
- Chart UI: убраны toggles Call/Put; master toggle Options + strike picker
- Chart: смена base/TF/checkbox/expiry rollover сохраняет viewport per `base+interval` (вместо unconditional `resetPriceScales` + `fitContent` на каждый reload)

### Deprecated

- `/api/polymarket/config` — используйте `/api/polymarket/events`; колонки `asset_config.polymarket_event_*` оставлены на переходный период
- `/api/candles?series=call|put` — legacy через `panel_snapshots`, оставлено для отладки

### Added (earlier unreleased)

- Polymarket: поле URL события в chart UI, API `GET/POST /api/polymarket/config`
- Polymarket ingestor: Gamma API, 6 strikes (3 ниже / 3 выше spot), multi-series на PM overlay
- Chart: пунктирные PM-линии по strikes (overlay scale `pm`, 0-100%), strike-метки в sidebar, единый crosshair tooltip

### Changed

- Chart: dual-pane LW Charts объединён в один экземпляр на `#chart-prices`; PM overlay scale `pm` (0-100%) вместо нижней панели; удалён sync между панелями и `#pm-empty` overlay

### Fixed

- Expiry normalization: symbol parse (00:00 UTC) и `deliveryTime`/`expireDate` приводятся к канону 08:00 UTC; mixed sources матчатся в одну expiry
- Chain API: при `spot=null` (нет panel snapshot) все контракты возвращают `otm=false` (OTM не вычисляется без spot)
- Chart: stale Y range after manual axis drag — superseded by layout persistence (restore per `chart_layout_<BASE>_<INTERVAL>`)
- Chart: linked time-scale no longer jumps on click/focus — panning and suppress-flag clear only after actual drag (pointermove), symmetric finish sync on both panes
- Chart: PM pane no longer snaps to right edge after pan left — symmetric `suppressPriceToPmSync` blocks stale price-led echo; final PM→price sync on pointerup
- Chart: PM pane time axis synced with futures via visible time range (not logical bar index); bucket timestamps returned as UTC unix seconds from SQL
- Chart: PM pane zoom sync — logical range + barSpacing co-synced with price chart (wheel/pinch); price wheel fallback listener
- Chart: candlestick wicks visible (`borderVisible: false`); non-flat bucket high/low preserved through `_chain_flat_candles`
- Chart: futures candles chain open from previous close when bucket has one tick (visible OHLC bodies on 5m)
- Chart: options collector parses Bybit symbol suffix (C/P) when strike/type fields absent — call/put lines populate
- Chart UI: infinite scroll no longer loops on empty history; PM pane empty state overlay; legend shows "Polymarket: awaiting data"

## 0.1.0 (2026-09-08)

### Added

- Новый проект `app-options/` (автономный от money-pulso screener; UI позже rebranded to Volta)
- PostgreSQL schema: instrument_snapshots, panel_snapshots, polymarket_snapshots, asset_config
- Ingestor: Bybit futures + ATM options для BTC/ETH/SOL (unicex PyPI)
- FastAPI panel с SessionMiddleware auth
- REST API: /health, /api/chart/batch, /api/candles, /api/probability, /api/panel/latest, /api/meta/assets
- Frontend: dual-pane Lightweight Charts v4, asset selector, TF toolbar, infinite scroll
- Docker compose: postgres + api + nginx
- Документация в docs/

### Known limitations

- HTTPS port 443 disabled in default compose
- SOL options availability depends on Bybit
- PM history appears after ingest interval once event URL is saved
