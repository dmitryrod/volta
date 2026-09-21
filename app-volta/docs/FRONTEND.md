# Frontend

## Stack

- Jinja2 templates: `login.html`, `chart.html`
- TradingView Lightweight Charts v4 (CDN)
- Vanilla JS: `frontend/static/js/chart.js`

## Auth flow

1. Неавторизованный пользователь на `/chart` -> redirect `/login`
2. POST `/login` -> signed session cookie
3. POST `/logout` -> очистка сессии

## Chart layout (panes and scales)

| Pane | Series | Scale |
|------|--------|-------|
| 0 (prices) | Futures candlestick | right (USD) |
| 0 | Option lines (multi-strike) | left (USD ask) |
| 0 | Polymarket Yes (per strike) | pm (0-100%) |

## Chart layout persistence (viewport)

Сохранение pan/zoom и price scales в `sessionStorage` per `base` + `interval`.

| Key / symbol | Назначение |
|--------------|------------|
| `chart_layout_<BASE>_<INTERVAL>` | JSON layout v1, напр. `chart_layout_BTC_5m` |
| `layoutStorageKey(base, interval)` | Строит ключ из `STORAGE_LAYOUT_PREFIX` |
| `captureChartLayout()` / `writeChartLayout()` | LWC state -> sessionStorage |
| `readChartLayout()` / `applyChartLayout()` | sessionStorage -> LWC |
| `debouncedSaveLayout()` / `persistChartLayout()` | Debounce **400 ms** (`LAYOUT_SAVE_DEBOUNCE_MS`); no-op при `loading` / `layoutRestoring`; merge price scales из existing при любом save |
| `flushSaveLayout(base, interval)` | Немедленный save перед `setBase` / `setTimeframe` / reload chart (явный ключ до смены) |
| `scheduleSyncPinnedAndSave()` | rAF x2 после `pointerup`/`wheel` — sync pin после commit LWC, затем debounced save |
| `sanitizeLayoutPriceScales()` | При read **после** `setData`: `autoScale:false` + invalid/absurd `visibleRange` -> `autoScale:true`; left — plausibility vs **mid сохранённого left range** (fallback live option ref); right — vs futures ref |
| `getLeftReferencePrice()` / `getLeftReferencePriceFromLayout()` | Ref для left guard: при наличии layout — mid saved left range; иначе live option premium (pinned / last point), не futures spot |
| `isPlausibleLeftPriceRange()` / `isPlausibleRightPriceRange()` / `isPersistablePriceRange()` | Guard pin: left — span/abs vs option ref; right — vs futures ref; left не sync без drag left axis (`leftScaleUserInteracted`) или wheel над left axis; right — без wheel/pointer на chart (`rightScaleUserInteracted`) или `autoScale:false` |
| `layoutRestoreGeneration` | Инкремент при `loadChart(reset=true)`; отменяет stale rAF-restore предыдущего тикера (без `fitContent` на новом) |
| `layoutSwitchInProgress` | `true` между `flushSaveLayout(prev)` и завершением `loadChart` при смене base или TF; блокирует debounced save/sync, пока chart ещё показывает предыдущий base/TF, а `chartStore.base` / `chartStore.interval` уже новые |
| `priceScaleAtPointer(event)` | Hit-test: left axis (`offsetX <= leftWidth`), right axis (`offsetX >= width - rightWidth`); wheel/pointerdown помечают `*ScaleUserInteracted` только на соответствующей оси |
| `applyUserInteractedFlagsFromLayout()` | После restore: сброс + восстановление `leftScaleUserInteracted` / `rightScaleUserInteracted` из сохранённых manual pins |
| `beginLayoutRestore()` / `endLayoutRestore()` | Блок save до restore; `end` через debounce+50 ms после apply |
| `restoreOrFitChartLayout()` | Restore или fallback `fitContent` |

Сохраняемый payload (v1):

```json
{
  "v": 1,
  "timeScale": { "visibleLogicalRange": { "from": 120.5, "to": 500.0 } },
  "priceScales": {
    "right": { "autoScale": false, "visibleRange": { "from": 2400, "to": 2600 } },
    "left": { "autoScale": true, "visibleRange": null },
    "pm": { "autoScale": true, "visibleRange": null }
  }
}
```

LWC v4.2 time scale: `getVisibleLogicalRange()` / `setVisibleLogicalRange()`, `getVisibleRange()` / `setVisibleRange()`. Restore time scale: до 12 rAF-попыток — сначала `visibleLogicalRange` (6 попыток), затем `visibleTimeRange` (unix sec); verify по logical **или** time range.

Price scale (LWC 4.2 limitation): у `priceScale()` **нет** `getVisibleRange` / `setVisibleRange` (только `applyOptions`, `options`, `width`). Рабочий обход:

| Шаг | API |
|-----|-----|
| Capture (manual Y zoom) | `scheduleSyncPinnedAndSave()` (rAF x2) на `pointerup`/`wheel`; `syncPinnedPriceScalesFromViewport()` при `autoScale === false` или при изменении viewport vs in-memory pin; `referenceSeries.coordinateToPrice(y)` |
| Restore | `pinnedPriceScaleRanges[scaleId]` + `autoscaleInfoProvider` на series (`right` -> futures, `left` -> option lines, `pm` -> PM lines); scale остаётся `autoScale: true`, provider фиксирует `priceRange` |
| Reset / first visit | `clearPinnedPriceScaleRanges()` + `autoScale: true` |

Reference series: `right` — futures candlestick; `left` — первая option line с данными; `pm` — первая PM line. PM без manual pin: `pmAutoscaleInfo` (0-100).

Poisoned state guard: если `autoScale: false`, но coordinate capture не дал range — в storage пишется `autoScale: true` (не сохраняем `visibleRange: null` с manual flag). Left scale: `coordinateToPrice` на option reference series при Y-zoom правой шкалы даёт мусор (±10^9); `syncPinnedPriceScalesFromViewport` не трогает left без `leftScaleUserInteracted` (pointer/wheel над left axis) или `autoScale:false` на left; plausibility vs **option** ref (не futures spot — иначе premiums $50–$200 отбрасываются). Right scale: `coordinateToPrice` на futures series в неверном layout state даёт мусор (billions/e+30); plausibility guard + `rightScaleUserInteracted` (wheel/pointer вне left axis); absurd ranges сбрасываются при read/restore/toggle.

### Save triggers

- `subscribeVisibleLogicalRangeChange` в `setupLayoutPersistence()` (тот же handler, что infinite scroll prepend)
- `pointerup` / `wheel` на `#chart-prices` (price-scale drag / zoom)
- `flushSaveLayout(base, interval)` при смене base, TF, options/PM reload
- `pagehide` / `visibilitychange(hidden)` -> `flushSaveLayout()` (без аргументов; handler не передаёт event как base)

Save подавляется при `chartStore.loading` и `layoutRestoring` (включая окно debounce+50 ms после restore).

### Restore rules

| Сценарий | Поведение |
|----------|-----------|
| `applyBatchData(..., prepend=false)` и ключ есть | `beginLayoutRestore` до `setData` -> rAF x2 -> до 12 попыток `applyChartLayout` (logical, затем time) + verify -> `applyToggles` -> `applyPriceScalesFromLayout` (pinned ranges + `refreshPinnedPriceScales`) |
| `applyBatchData(..., prepend=false)` и ключа нет | `resetPriceScales` + `fitContent` (first visit) |
| `applyBatchData(..., prepend=true)` | Без restore и без fit (infinite scroll) |
| `applyLiveUpdate` | Без restore, fit, reset |
| Invalid saved range | try/catch -> fallback `fitContent` |

Expiry rollover и смена options checkbox: `loadChart(true)` -> restore layout для текущего `base+interval`.

## Toolbar

- Asset tabs: BTC / ETH / SOL — `selected_base` в sessionStorage
- Timeframe: 1m .. 1d — `selected_interval`
- Options dropdown: кнопка Options + panel Call | Put; master toggle `#toggle-options` (visibility линий)
- Toggles: Futures / Options / Polymarket visibility
- Logout

## Options state (`chart.js`)

| Key / variable | Назначение |
|----------------|------------|
| `selected_option_symbols_<BASE>` | JSON array выбранных Bybit symbols (`STORAGE_OPTION_SYMBOLS + base`) |
| `selected_option_expiry_<BASE>` | ISO expiry из chain API (`STORAGE_OPTION_EXPIRY + base`) |
| `optionSeriesMap` | `Map`: symbol -> `{ series, label, strike, option_type }` (LWC LineSeries) |
| `seriesCache.options` | symbol -> points[] |
| `chartStore.optionsChain` | последний ответ chain API |
| `chartStore.selectedOptionSymbols` | активный список symbols для batch |

### Options dropdown

- Кнопка `#options-menu-btn` открывает `#options-panel` (Call | Put колонки).
- Строка OTM: CSS class `options-row otm` на strike label.
- Checkbox change: обновить storage, `loadChart(true)` (полный reset + batch с новым `symbols`).

### Default selection (`pickDefaultSymbols`)

1. `GET /api/options/chain?base=X` через `syncOptionsChain` (вызывается при `loadChart(reset=true)`).
2. Если storage пуст или expiry сменился: 1 OTM call (min strike среди `otm=true`) + 1 OTM put (max strike среди `otm=true`).
3. Fallback без OTM flags: ближайший к spot по `|strike - spot|` — **только если `chain.spot != null`**. При `spot=null` OTM-фильтр пуст, fallback не срабатывает → selection может остаться пустой.

### Expiry rollover

При `chain.expiry !== selected_option_expiry_<BASE>`: очистить symbols storage, default pair, удалить stale entries из `optionSeriesMap`, reload chart.

Symbols из storage фильтруются по текущему chain (`validSymbols`); невалидные отбрасываются без ошибки.

### Visibility

- Master toggle `#toggle-options`: показывает/скрывает option lines и left price scale (USD ask).
- Left scale visible только при toggle ON и наличии option data.

## Datafeed

Два пути к `GET /api/chart/batch` (см. `ARCHITECTURE.md`):

| Путь | Функция | Параметры | Клиент |
|------|---------|-----------|--------|
| Full batch | `loadChart(reset)` | `limit=500`, без `from`; prepend: `to=oldestTime-1` | `applyBatchData` |
| Tail poll (live) | `pollLiveUpdate()` | `from=newestTime-bucketSec`, `limit=20` | `applyLiveUpdate` |

`symbols` — выбранные option symbols через запятую (из `chartStore.selectedOptionSymbols`).

При `loadChart(reset=true)` (смена base/TF/checkbox): сначала `syncOptionsChain`, затем full batch; после успеха — `startLivePolling()`.

При смене base или TF: полная перезагрузка (`setData`), layout restore по ключу `chart_layout_<BASE>_<INTERVAL>`.

Infinite history: `subscribeVisibleLogicalRangeChange`; при `range.from < 5` batch с `to=oldestTime-1` (`prepend=true`). Prepend подавлен при `layoutRestoring` (иначе default viewport после `setData` запускает prepend до restore).

## Live refresh

| Layer | Transport | Scope |
|-------|-----------|-------|
| Futures | `EventSource` `/api/chart/stream?base=&interval=` | `applyFuturesSseUpdate` → `futuresSeries.update` |
| Options / PM | Polling `GET /api/chart/batch?from=` | `applyLiveUpdate` (без futures) |

| Symbol | Роль |
|--------|------|
| `startFuturesSSE()` / `stopFuturesSSE()` | SSE lifecycle per base+interval |
| `applyFuturesSseUpdate(candle, confirmed)` | merge live futures bar без viewport reset |
| `startLivePolling()` / `stopLivePolling()` | Options/PM timer |
| `livePollTick()` | Guard: `document.hidden`, `chartStore.loading` |

Ingestor держит 18 WS topics (3 symbols × 6 TF) — смена TF на графике мгновенная (данные уже в `KlineHub`).

Пауза SSE и poll: `document.hidden`; рестарт при возврате на вкладку. Старт после layout restore (`startLiveFeedsIfPending` в `finishRestore` / sync `restoreOrFitChartLayout`); стоп при `loadChart(reset=true)`.

## Polymarket

Каталог событий per base (до 10 URL): toolbar dropdown **Polymarket** — textarea bulk import + radio list. API: `GET/POST /api/polymarket/events`.

| Ключ sessionStorage | Значение |
|---------------------|----------|
| `selected_pm_event_<BASE>` | slug выбранного события для графика |

| Действие | Поведение |
|----------|-----------|
| Import URLs на ETH | все события в списке; ingest по всем; на графике — выбранное radio |
| Switch на BTC | свой каталог и selection; ETH events не видны |
| Radio change | `clearPmOverlay()` + `loadChart(true)` с `pm_event_slug` |
| F5 / TF switch | selection и layout per base не смешиваются |

`changeChartBase` / `changeChartInterval`: `cancelPendingLayoutSave` + `flushSaveLayout(prevBase, prevInterval)` **до** смены `chartStore.base` / `chartStore.interval`; `layoutSwitchInProgress` на время `loadChart(true)` (base: плюс `clearPmOverlay` + `await loadPmEventsForBase`). `fetchBatch` / `pollLiveUpdate` передают `pm_event_slug` при выбранном событии.

Countdown (`#pm-expiry-countdown`) — для выбранного события. Strike labels в sidebar (`#pm-strike-labels`). Пустой PM — legend «awaiting ingest» или import в dropdown.

Цвета PM-линий: ярко-жёлтый (`#ffee58`, `PM_ATM_COLOR`) — strike с Yes% ближе всего к 50 (последняя точка ряда); остальные — стабильные вторичные цвета по strike/market_id. Пересчёт при full load, prepend и live poll; не зависит от порядка `series` в batch.

## SOL options

Если chain пустой — dropdown без strikes; futures отображается.
