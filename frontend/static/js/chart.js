/**
 * TradingView Lightweight Charts v4 — single-pane chart with batch datafeed.
 */
(function () {
  "use strict";

  const STORAGE_BASE = "selected_base";
  const STORAGE_INTERVAL = "selected_interval";
  const STORAGE_OPTION_SYMBOLS = "selected_option_symbols_";
  const STORAGE_OPTION_EXPIRY = "selected_option_expiry_";
  const STORAGE_PM_EVENT = "selected_pm_event_";
  const STORAGE_LAYOUT_PREFIX = "chart_layout_";
  const DEFAULT_BASE = "BTC";
  const DEFAULT_INTERVAL = "5m";
  const BATCH_LIMIT = 500;
  const LIVE_UPDATE_LIMIT = 20;
  const LAYOUT_SAVE_DEBOUNCE_MS = 400;
  const LAYOUT_RESTORE_MAX_ATTEMPTS = 12;
  const LAYOUT_PRICE_SCALE_IDS = ["right", "left", "pm"];

  const INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
  };

  const POLL_INTERVAL_MS = {
    "1m": 30000,
    "5m": 60000,
    "15m": 120000,
    "1h": 300000,
    "4h": 600000,
    "1d": 900000,
  };

  const PM_ATM_COLOR = "#ffee58";
  const PM_SECONDARY_COLORS = [
    "#ffa726",
    "#42a5f5",
    "#78909c",
    "#ba68c8",
    "#4dd0e1",
  ];

  const CALL_COLORS = ["#26a69a", "#2bbbad", "#00897b", "#4db6ac", "#80cbc4"];
  const PUT_COLORS = ["#ef5350", "#e53935", "#c62828", "#ff7043", "#ff8a65"];

  const chartStore = {
    base: sessionStorage.getItem(STORAGE_BASE) || DEFAULT_BASE,
    interval: sessionStorage.getItem(STORAGE_INTERVAL) || DEFAULT_INTERVAL,
    loading: false,
    pendingReload: false,
    oldestTime: null,
    newestTime: null,
    hasMore: true,
    pmEventSlug: null,
    pmEventUrl: null,
    pmEventEndDate: null,
    pmEvents: [],
    optionsExpiry: null,
    optionsChain: null,
    selectedOptionSymbols: [],
  };

  const seriesCache = {
    futures: [],
    options: {},
    pm: {},
  };

  const seriesMeta = new WeakMap();
  const pmSeriesMap = new Map();
  const optionSeriesMap = new Map();

  let priceChart = null;
  let pmCountdownTimer = null;
  let futuresSeries = null;
  let layoutSaveTimer = null;
  let livePollTimer = null;
  let pollInFlight = false;
  let futuresEventSource = null;
  let layoutRestoring = false;
  let layoutRestoreGeneration = 0;
  let layoutSwitchInProgress = false;
  let liveFeedsPending = false;

  const pinnedPriceScaleRanges = {
    right: null,
    left: null,
    pm: null,
  };

  let leftScaleUserInteracted = false;
  let rightScaleUserInteracted = false;

  const LEFT_SCALE_MAX_ABS_MULTIPLIER = 5;
  const LEFT_SCALE_MAX_SPAN_MULTIPLIER = 4;
  const LEFT_SCALE_MID_DEVIATION_FACTOR = 10;
  const LEFT_SCALE_ABS_FALLBACK_MAX = 1e6;
  const LEFT_SCALE_SPAN_FALLBACK_MAX = 1e6;
  const RIGHT_SCALE_MAX_ABS_MULTIPLIER = 5;
  const RIGHT_SCALE_MAX_SPAN_MULTIPLIER = 4;
  const RIGHT_SCALE_MID_DEVIATION_FACTOR = 10;
  const RIGHT_SCALE_ABS_FALLBACK_MAX = 1e6;
  const RIGHT_SCALE_SPAN_FALLBACK_MAX = 1e6;
  const PM_RANGE_MIN = -5;
  const PM_RANGE_MAX = 105;
  const PM_MIN_SPAN = 10;

  const chartOptions = {
    layout: {
      background: { color: "#0f1117" },
      textColor: "#9aa0a6",
    },
    grid: {
      vertLines: { color: "#1f2430" },
      horzLines: { color: "#1f2430" },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "#2a2f3d", autoScale: true },
    leftPriceScale: { visible: false, borderColor: "#2a2f3d", autoScale: true },
    timeScale: {
      borderColor: "#2a2f3d",
      timeVisible: true,
      secondsVisible: false,
      fixLeftEdge: false,
      fixRightEdge: false,
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    },
  };

  function registerSeriesMeta(series, meta) {
    seriesMeta.set(series, meta);
  }

  function formatSeriesValue(meta, dataPoint) {
    if (!dataPoint) return null;
    if (meta.type === "candle") {
      return Number(dataPoint.close).toFixed(2);
    }
    return Number(dataPoint.value).toFixed(2);
  }

  function pinnedAutoscaleInfo(scaleId) {
    return function (baseAutoscale) {
      const pinned = pinnedPriceScaleRanges[scaleId];
      if (isPersistablePriceRange(scaleId, pinned)) {
        return {
          priceRange: { minValue: pinned.from, maxValue: pinned.to },
        };
      }
      if (scaleId === "left" && pinned) {
        pinnedPriceScaleRanges.left = null;
      }
      if (scaleId === "right" && pinned) {
        pinnedPriceScaleRanges.right = null;
      }
      return baseAutoscale();
    };
  }

  function pmAutoscaleInfo(baseAutoscale) {
    const pinned = pinnedPriceScaleRanges.pm;
    if (isPersistablePriceRange("pm", pinned)) {
      return {
        priceRange: { minValue: pinned.from, maxValue: pinned.to },
      };
    }
    if (typeof baseAutoscale === "function") {
      const base = baseAutoscale();
      if (base && base.priceRange) {
        return base;
      }
    }
    return {
      priceRange: { minValue: 0, maxValue: 100 },
    };
  }

  function isPmOverlayEnabled() {
    const pmToggle = document.getElementById("toggle-pm");
    return Boolean(pmToggle && pmToggle.checked);
  }

  function isOptionsOverlayEnabled() {
    const optToggle = document.getElementById("toggle-options");
    return Boolean(optToggle && optToggle.checked);
  }

  function optionStorageKey(base) {
    return STORAGE_OPTION_SYMBOLS + base;
  }

  function optionExpiryStorageKey(base) {
    return STORAGE_OPTION_EXPIRY + base;
  }

  function optionColor(optionType, index) {
    const palette = optionType === "put" ? PUT_COLORS : CALL_COLORS;
    return palette[index % palette.length];
  }

  function initCharts() {
    const pricesEl = document.getElementById("chart-prices");

    if (!pricesEl) {
      console.error("chart-prices element not found");
      return;
    }

    priceChart = LightweightCharts.createChart(pricesEl, {
      ...chartOptions,
      width: pricesEl.clientWidth,
      height: pricesEl.clientHeight,
    });

    futuresSeries = priceChart.addCandlestickSeries({
      priceScaleId: "right",
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickVisible: true,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
      autoscaleInfoProvider: pinnedAutoscaleInfo("right"),
    });
    registerSeriesMeta(futuresSeries, {
      name: "Futures",
      type: "candle",
      color: "#26a69a",
    });

    applyPmPriceScale();
    setupInfiniteScroll();
    setupLayoutPersistence();
    setupCrosshairTooltip();
    setupResize(pricesEl);
  }

  function pmSecondaryColor(index) {
    return PM_SECONDARY_COLORS[index % PM_SECONDARY_COLORS.length];
  }

  function pmLatestValue(marketId, pointsFallback) {
    const cached = seriesCache.pm[marketId];
    if (cached && cached.length) {
      return cached[cached.length - 1].value;
    }
    if (pointsFallback && pointsFallback.length) {
      return pointsFallback[pointsFallback.length - 1].value;
    }
    return null;
  }

  function comparePmStrikeTieBreak(a, b) {
    if (a.strike == null && b.strike == null) {
      return a.marketId < b.marketId ? -1 : a.marketId > b.marketId ? 1 : 0;
    }
    if (a.strike == null) return 1;
    if (b.strike == null) return -1;
    if (a.strike !== b.strike) return a.strike - b.strike;
    return a.marketId < b.marketId ? -1 : a.marketId > b.marketId ? 1 : 0;
  }

  function resolvePmColorMap(seriesList) {
    const entries = [];
    (seriesList || []).forEach(function (item) {
      const marketId = item.market_id;
      if (!marketId) return;
      const raw = pmLatestValue(marketId, item.points);
      if (raw == null || !Number.isFinite(Number(raw))) return;
      entries.push({
        marketId: marketId,
        strike: item.strike,
        value: Number(raw),
      });
    });

    const colorMap = new Map();
    if (!entries.length) return colorMap;

    let atmEntry = entries[0];
    let atmDist = Math.abs(atmEntry.value - 50);
    for (let i = 1; i < entries.length; i++) {
      const candidate = entries[i];
      const dist = Math.abs(candidate.value - 50);
      if (dist < atmDist) {
        atmEntry = candidate;
        atmDist = dist;
      } else if (dist === atmDist && comparePmStrikeTieBreak(candidate, atmEntry) < 0) {
        atmEntry = candidate;
      }
    }

    colorMap.set(atmEntry.marketId, PM_ATM_COLOR);
    entries
      .filter(function (entry) {
        return entry.marketId !== atmEntry.marketId;
      })
      .sort(comparePmStrikeTieBreak)
      .forEach(function (entry, index) {
        colorMap.set(entry.marketId, pmSecondaryColor(index));
      });
    return colorMap;
  }

  function applyPmSeriesColors(seriesList) {
    const colorMap = resolvePmColorMap(seriesList);
    (seriesList || []).forEach(function (item, index) {
      const marketId = item.market_id;
      if (!marketId) return;
      const points = seriesCache.pm[marketId] || item.points || [];
      if (!points.length) return;
      const color = colorMap.get(marketId) || pmSecondaryColor(index);
      ensurePmSeries(item, color);
    });
  }

  function applyPmPriceScale(preserveUserScale) {
    if (!priceChart) return;
    const pmVisible = isPmOverlayEnabled() && pmSeriesMap.size > 0;
    const patch = {
      scaleMargins: { top: 0.05, bottom: 0.05 },
      borderColor: "#2a2f3d",
      visible: pmVisible,
    };
    if (!preserveUserScale) {
      patch.autoScale = true;
    }
    priceChart.priceScale("pm").applyOptions(patch);
    pmSeriesMap.forEach(function (entry) {
      entry.series.applyOptions({ autoscaleInfoProvider: pmAutoscaleInfo });
    });
  }

  function clearPinnedPriceScaleRanges() {
    pinnedPriceScaleRanges.right = null;
    pinnedPriceScaleRanges.left = null;
    pinnedPriceScaleRanges.pm = null;
  }

  function getPricePaneHeight() {
    if (!priceChart) return 0;
    const chartEl = priceChart.chartElement();
    const totalHeight = chartEl ? chartEl.clientHeight : 0;
    const timeScaleHeight = priceChart.timeScale().height();
    return Math.max(1, totalHeight - timeScaleHeight);
  }

  function referenceSeriesForScale(scaleId) {
    if (scaleId === "right") {
      return futuresSeries;
    }
    if (scaleId === "left") {
      let firstSeries = null;
      optionSeriesMap.forEach(function (entry, symbol) {
        if (firstSeries) return;
        const points = seriesCache.options[symbol];
        if (points && points.length) {
          firstSeries = entry.series;
        }
      });
      return firstSeries;
    }
    if (scaleId === "pm") {
      let firstSeries = null;
      pmSeriesMap.forEach(function (entry) {
        if (!firstSeries) {
          firstSeries = entry.series;
        }
      });
      return firstSeries;
    }
    return null;
  }

  function capturePriceRangeViaCoordinates(scaleId) {
    const referenceSeries = referenceSeriesForScale(scaleId);
    if (!referenceSeries) return null;
    const paneHeight = getPricePaneHeight();
    const topCoord = 1;
    const bottomCoord = Math.max(topCoord + 1, paneHeight - 2);
    let topPrice = referenceSeries.coordinateToPrice(topCoord);
    let bottomPrice = referenceSeries.coordinateToPrice(bottomCoord);
    if (topPrice == null || bottomPrice == null) return null;
    topPrice = Number(topPrice);
    bottomPrice = Number(bottomPrice);
    if (!Number.isFinite(topPrice) || !Number.isFinite(bottomPrice)) return null;
    if (topPrice === bottomPrice) return null;
    return {
      from: Math.min(topPrice, bottomPrice),
      to: Math.max(topPrice, bottomPrice),
    };
  }

  function refreshPinnedPriceScales() {
    if (!priceChart) return;
    if (futuresSeries) {
      futuresSeries.applyOptions({});
    }
    optionSeriesMap.forEach(function (entry) {
      entry.series.applyOptions({});
    });
    pmSeriesMap.forEach(function (entry) {
      entry.series.applyOptions({});
    });
  }

  function getFuturesReferencePrice() {
    const futures = seriesCache.futures;
    if (!futures || !futures.length) return null;
    const close = Number(futures[futures.length - 1].close);
    return Number.isFinite(close) && close > 0 ? close : null;
  }

  function getLeftReferencePriceFromLayout(layout) {
    if (!layout || !layout.priceScales || !layout.priceScales.left) return null;
    const leftRange = layout.priceScales.left.visibleRange;
    if (!isValidPriceRange(leftRange)) return null;
    const mid = (leftRange.from + leftRange.to) / 2;
    return Number.isFinite(mid) && mid > 0 ? mid : null;
  }

  function getLiveLeftReferencePrice() {
    const pinned = pinnedPriceScaleRanges.left;
    if (isValidPriceRange(pinned)) {
      const mid = (pinned.from + pinned.to) / 2;
      if (Number.isFinite(mid) && mid > 0) return mid;
    }
    let lastValue = null;
    Object.keys(seriesCache.options).forEach(function (sym) {
      const points = seriesCache.options[sym];
      if (!points || !points.length) return;
      const val = Number(points[points.length - 1].value);
      if (Number.isFinite(val) && val > 0) {
        lastValue = val;
      }
    });
    if (lastValue != null) return lastValue;
    let min = Infinity;
    let max = -Infinity;
    Object.keys(seriesCache.options).forEach(function (sym) {
      const points = seriesCache.options[sym];
      if (!points || !points.length) return;
      points.forEach(function (pt) {
        const val = Number(pt.value);
        if (Number.isFinite(val)) {
          min = Math.min(min, val);
          max = Math.max(max, val);
        }
      });
    });
    if (min < max) return (min + max) / 2;
    return null;
  }

  function getLeftReferencePrice(layout) {
    if (layout) {
      const layoutRef = getLeftReferencePriceFromLayout(layout);
      if (layoutRef != null) return layoutRef;
    }
    return getLiveLeftReferencePrice();
  }

  function getLeftReferencePriceForSanitize(layout) {
    if (layout) {
      const layoutRef = getLeftReferencePriceFromLayout(layout);
      if (layoutRef != null) return layoutRef;
    }
    return getLiveLeftReferencePrice();
  }

  function getRightReferencePriceForSanitize() {
    return getFuturesReferencePrice();
  }

  function referencePriceFromLayout(layout) {
    const futuresRef = getFuturesReferencePrice();
    if (futuresRef != null) return futuresRef;
    if (!layout || !layout.priceScales || !layout.priceScales.right) return null;
    const rightRange = layout.priceScales.right.visibleRange;
    if (!isValidPriceRange(rightRange)) return null;
    const mid = (rightRange.from + rightRange.to) / 2;
    return Number.isFinite(mid) && mid > 0 ? mid : null;
  }

  function referencePriceForScale(scaleId, layout) {
    if (scaleId === "left") {
      return getLeftReferencePrice(layout);
    }
    if (scaleId === "right") {
      return getRightReferencePrice() || referencePriceFromLayout(layout);
    }
    return null;
  }

  function isPlausiblePriceRange(range, refPrice, multipliers) {
    if (!isValidPriceRange(range)) return false;
    const span = Math.abs(range.to - range.from);
    if (refPrice != null && Number.isFinite(refPrice) && refPrice > 0) {
      const absMax = refPrice * multipliers.abs;
      const maxSpan = refPrice * multipliers.span;
      if (Math.abs(range.from) > absMax || Math.abs(range.to) > absMax) return false;
      if (span > maxSpan) return false;
      const mid = (range.from + range.to) / 2;
      if (mid > refPrice * multipliers.mid || mid < refPrice / multipliers.mid) {
        return false;
      }
      return true;
    }
    if (Math.max(Math.abs(range.from), Math.abs(range.to)) > multipliers.absFallback) return false;
    return span <= multipliers.spanFallback;
  }

  const LEFT_SCALE_MULTIPLIERS = {
    abs: LEFT_SCALE_MAX_ABS_MULTIPLIER,
    span: LEFT_SCALE_MAX_SPAN_MULTIPLIER,
    mid: LEFT_SCALE_MID_DEVIATION_FACTOR,
    absFallback: LEFT_SCALE_ABS_FALLBACK_MAX,
    spanFallback: LEFT_SCALE_SPAN_FALLBACK_MAX,
  };

  const RIGHT_SCALE_MULTIPLIERS = {
    abs: RIGHT_SCALE_MAX_ABS_MULTIPLIER,
    span: RIGHT_SCALE_MAX_SPAN_MULTIPLIER,
    mid: RIGHT_SCALE_MID_DEVIATION_FACTOR,
    absFallback: RIGHT_SCALE_ABS_FALLBACK_MAX,
    spanFallback: RIGHT_SCALE_SPAN_FALLBACK_MAX,
  };

  function isPlausibleLeftPriceRange(range, refPrice) {
    return isPlausiblePriceRange(range, refPrice, LEFT_SCALE_MULTIPLIERS);
  }

  function getRightReferencePrice() {
    const futuresRef = getFuturesReferencePrice();
    if (futuresRef != null) return futuresRef;
    const pinned = pinnedPriceScaleRanges.right;
    if (isValidPriceRange(pinned)) {
      const mid = (pinned.from + pinned.to) / 2;
      if (Number.isFinite(mid) && mid > 0) return mid;
    }
    const futures = seriesCache.futures;
    if (!futures || !futures.length) return null;
    let min = Infinity;
    let max = -Infinity;
    futures.forEach(function (bar) {
      const lo = Number(bar.low);
      const hi = Number(bar.high);
      if (Number.isFinite(lo)) min = Math.min(min, lo);
      if (Number.isFinite(hi)) max = Math.max(max, hi);
    });
    if (min < max) return (min + max) / 2;
    return null;
  }

  function isPlausibleRightPriceRange(range, refPrice) {
    const ref = refPrice != null ? refPrice : getRightReferencePrice();
    return isPlausiblePriceRange(range, ref, RIGHT_SCALE_MULTIPLIERS);
  }

  function isPersistablePriceRange(scaleId, range, layout) {
    if (!isValidPriceRange(range)) return false;
    if (scaleId === "left") {
      const ref = getLeftReferencePrice(layout);
      return isPlausibleLeftPriceRange(range, ref);
    }
    if (scaleId === "right") {
      const ref = getRightReferencePrice() || referencePriceFromLayout(layout);
      return isPlausibleRightPriceRange(range, ref);
    }
    if (scaleId === "pm") {
      const span = range.to - range.from;
      return (
        range.from >= PM_RANGE_MIN &&
        range.to <= PM_RANGE_MAX &&
        span >= PM_MIN_SPAN
      );
    }
    return true;
  }

  function clearInvalidLeftPin(layout) {
    const pinned = pinnedPriceScaleRanges.left;
    if (!pinned) return;
    const ref = getLeftReferencePrice(layout);
    if (!isPlausibleLeftPriceRange(pinned, ref)) {
      pinnedPriceScaleRanges.left = null;
    }
  }

  function clearInvalidRightPin(refPrice) {
    const pinned = pinnedPriceScaleRanges.right;
    if (!pinned) return;
    const ref = refPrice != null ? refPrice : getRightReferencePrice();
    if (!isPlausibleRightPriceRange(pinned, ref)) {
      pinnedPriceScaleRanges.right = null;
    }
  }

  function clearInvalidPmPin() {
    const pinned = pinnedPriceScaleRanges.pm;
    if (!pinned) return;
    if (!isPersistablePriceRange("pm", pinned)) {
      pinnedPriceScaleRanges.pm = null;
    }
  }

  function shouldSyncLeftScaleFromViewport(scale) {
    if (!scale) return false;
    const opts = scale.options();
    if (opts.autoScale === false) return true;
    return leftScaleUserInteracted;
  }

  function shouldSyncRightScaleFromViewport(scale) {
    if (!scale) return false;
    const opts = scale.options();
    if (opts.autoScale === false) return true;
    return rightScaleUserInteracted;
  }

  function refreshPinnedPriceScalesIfNeeded() {
    if (!priceChart || layoutRestoring) return;
    const hasPin = LAYOUT_PRICE_SCALE_IDS.some(function (scaleId) {
      return isPersistablePriceRange(scaleId, pinnedPriceScaleRanges[scaleId]);
    });
    if (hasPin) {
      refreshPinnedPriceScales();
    }
  }

  function priceRangeDiffers(a, b) {
    if (!isValidPriceRange(a) || !isValidPriceRange(b)) return true;
    const span = Math.abs(a.to - a.from) || 1;
    const eps = Math.max(span * 1e-4, 1e-8);
    return (
      Math.abs(a.from - b.from) > eps || Math.abs(a.to - b.to) > eps
    );
  }

  function syncPinnedPriceScalesFromViewport() {
    if (!priceChart || layoutRestoring || layoutSwitchInProgress || chartStore.loading) {
      return;
    }
    LAYOUT_PRICE_SCALE_IDS.forEach(function (scaleId) {
      const scale = priceChart.priceScale(scaleId);
      const opts = scale.options();
      if (opts.visible === false) return;
      if (scaleId === "left" && !shouldSyncLeftScaleFromViewport(scale)) return;
      if (scaleId === "right" && !shouldSyncRightScaleFromViewport(scale)) return;
      if (scaleId === "pm" && pmSeriesMap.size === 0) return;
      const range = capturePriceRangeViaCoordinates(scaleId);
      if (!isPersistablePriceRange(scaleId, range)) return;
      if (opts.autoScale === false) {
        pinnedPriceScaleRanges[scaleId] = range;
        return;
      }
      const shouldSyncPin =
        (scaleId === "left" && shouldSyncLeftScaleFromViewport(scale)) ||
        (scaleId === "right" && shouldSyncRightScaleFromViewport(scale)) ||
        scaleId === "pm";
      if (!shouldSyncPin) return;
      const existing = pinnedPriceScaleRanges[scaleId];
      if (!isPersistablePriceRange(scaleId, existing) || priceRangeDiffers(range, existing)) {
        pinnedPriceScaleRanges[scaleId] = range;
      }
    });
  }

  function scheduleSyncPinnedAndSave() {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (!shouldPersistLayout()) return;
        syncPinnedPriceScalesFromViewport();
        debouncedSaveLayout();
      });
    });
  }

  function requestLiveFeedsAfterLayout() {
    liveFeedsPending = true;
  }

  function startLiveFeedsIfPending() {
    if (!liveFeedsPending || chartStore.loading || document.hidden) return;
    liveFeedsPending = false;
    startFuturesSSE();
    startLivePolling();
  }

  function resetPriceScales(hasOptions) {
    if (!priceChart) return;
    leftScaleUserInteracted = false;
    rightScaleUserInteracted = false;
    clearPinnedPriceScaleRanges();
    priceChart.priceScale("right").applyOptions({
      autoScale: true,
      scaleMargins: { top: 0.1, bottom: 0.1 },
    });
    priceChart.priceScale("left").applyOptions({
      autoScale: hasOptions,
      visible: hasOptions && isOptionsOverlayEnabled(),
      scaleMargins: { top: 0.1, bottom: 0.1 },
    });
    applyPmPriceScale();
  }

  function layoutStorageKey(base, interval) {
    return STORAGE_LAYOUT_PREFIX + base + "_" + interval;
  }

  function isValidLogicalRange(range) {
    return (
      range &&
      typeof range.from === "number" &&
      typeof range.to === "number" &&
      Number.isFinite(range.from) &&
      Number.isFinite(range.to)
    );
  }

  function isValidPriceRange(range) {
    return (
      range &&
      typeof range.from === "number" &&
      typeof range.to === "number" &&
      Number.isFinite(range.from) &&
      Number.isFinite(range.to)
    );
  }

  function sanitizeLayoutPriceScales(layout) {
    if (!layout || !layout.priceScales) return layout;
    LAYOUT_PRICE_SCALE_IDS.forEach(function (scaleId) {
      const saved = layout.priceScales[scaleId];
      if (!saved) return;
      const refPrice =
        scaleId === "left"
          ? getLeftReferencePriceForSanitize(layout)
          : scaleId === "right"
            ? getRightReferencePriceForSanitize()
            : null;
      const rangeInvalid =
        saved.autoScale === false &&
        (!isValidPriceRange(saved.visibleRange) ||
          (scaleId === "left" && !isPlausibleLeftPriceRange(saved.visibleRange, refPrice)) ||
          (scaleId === "right" && !isPlausibleRightPriceRange(saved.visibleRange, refPrice)) ||
          (scaleId === "pm" && !isPersistablePriceRange("pm", saved.visibleRange)));
      if (rangeInvalid) {
        layout.priceScales[scaleId] = { autoScale: true, visibleRange: null };
      }
    });
    return layout;
  }

  function applyUserInteractedFlagsFromLayout(layout) {
    leftScaleUserInteracted = false;
    rightScaleUserInteracted = false;
    if (!layout || !layout.priceScales) return;
    const left = layout.priceScales.left;
    const right = layout.priceScales.right;
    if (
      left &&
      left.autoScale === false &&
      isPersistablePriceRange("left", left.visibleRange, layout)
    ) {
      leftScaleUserInteracted = true;
    }
    if (
      right &&
      right.autoScale === false &&
      isPersistablePriceRange("right", right.visibleRange, layout)
    ) {
      rightScaleUserInteracted = true;
    }
  }

  function readChartLayout(base, interval) {
    try {
      const raw = sessionStorage.getItem(layoutStorageKey(base, interval));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed && parsed.v === 1) {
        return sanitizeLayoutPriceScales(parsed);
      }
      return null;
    } catch (_err) {
      return null;
    }
  }

  function isValidTimeRange(range) {
    return (
      range &&
      range.from != null &&
      range.to != null &&
      Number.isFinite(Number(range.from)) &&
      Number.isFinite(Number(range.to))
    );
  }

  function savedLayoutTimeRange(layout) {
    return layout && layout.timeScale && layout.timeScale.visibleLogicalRange;
  }

  function savedLayoutVisibleTimeRange(layout) {
    return layout && layout.timeScale && layout.timeScale.visibleTimeRange;
  }

  function hasRestorableLeftPriceScale(layout) {
    if (!layout || layout.v !== 1 || !layout.priceScales) return false;
    const left = layout.priceScales.left;
    return (
      left &&
      left.autoScale === false &&
      isPersistablePriceRange("left", left.visibleRange, layout)
    );
  }

  function hasRestorableLayout(layout) {
    if (!layout || layout.v !== 1) return false;
    return (
      isValidLogicalRange(savedLayoutTimeRange(layout)) ||
      isValidTimeRange(savedLayoutVisibleTimeRange(layout)) ||
      hasRestorableLeftPriceScale(layout)
    );
  }

  function hasSavedLayoutForCurrent() {
    return hasRestorableLayout(readChartLayout(chartStore.base, chartStore.interval));
  }

  function cancelPendingLayoutSave() {
    if (layoutSaveTimer) {
      clearTimeout(layoutSaveTimer);
      layoutSaveTimer = null;
    }
  }

  function beginLayoutRestore() {
    cancelPendingLayoutSave();
    layoutRestoring = true;
  }

  function endLayoutRestore() {
    setTimeout(function () {
      layoutRestoring = false;
    }, LAYOUT_SAVE_DEBOUNCE_MS + 50);
  }

  function shouldPersistLayout() {
    return !chartStore.loading && !layoutRestoring && !layoutSwitchInProgress;
  }

  function writeChartLayout(base, interval, layout) {
    if (!layout || !hasRestorableLayout(layout)) return;
    layout = sanitizeLayoutPriceScales(
      JSON.parse(JSON.stringify(layout))
    );
    let timeRange = savedLayoutTimeRange(layout);
    let visibleTimeRange = savedLayoutVisibleTimeRange(layout);
    if (!isValidLogicalRange(timeRange) && !isValidTimeRange(visibleTimeRange)) {
      const existing = readChartLayout(base, interval);
      const existingLogical = savedLayoutTimeRange(existing);
      const existingTime = savedLayoutVisibleTimeRange(existing);
      if (isValidLogicalRange(existingLogical) || isValidTimeRange(existingTime)) {
        layout = {
          v: 1,
          timeScale: {
            visibleLogicalRange: isValidLogicalRange(existingLogical) ? existingLogical : null,
            visibleTimeRange: isValidTimeRange(existingTime) ? existingTime : null,
          },
          priceScales: layout.priceScales || (existing && existing.priceScales) || {},
        };
      } else if (hasRestorableLeftPriceScale(layout)) {
        layout = {
          v: 1,
          timeScale: {
            visibleLogicalRange: null,
            visibleTimeRange: null,
          },
          priceScales: layout.priceScales,
        };
      } else {
        return;
      }
    }
    try {
      sessionStorage.setItem(layoutStorageKey(base, interval), JSON.stringify(layout));
    } catch (_err) {
      // sessionStorage quota or private mode
    }
  }

  function capturePriceScaleState(scaleId) {
    if (!priceChart) {
      return { autoScale: true, visibleRange: null };
    }
    if (scaleId === "pm" && pmSeriesMap.size === 0) {
      return { autoScale: true, visibleRange: null };
    }
    const pinned = pinnedPriceScaleRanges[scaleId];
    if (isPersistablePriceRange(scaleId, pinned)) {
      return {
        autoScale: false,
        visibleRange: { from: pinned.from, to: pinned.to },
      };
    }
    const scale = priceChart.priceScale(scaleId);
    const opts = scale.options();
    if (opts.visible === false) {
      return { autoScale: opts.autoScale !== false, visibleRange: null };
    }
    if (scaleId === "left" && pinned) {
      pinnedPriceScaleRanges.left = null;
    }
    if (scaleId === "right" && pinned) {
      pinnedPriceScaleRanges.right = null;
    }
    const autoScale = opts.autoScale !== false;
    if (autoScale) {
      return { autoScale: true, visibleRange: null };
    }
    const visibleRange = capturePriceRangeViaCoordinates(scaleId);
    if (isPersistablePriceRange(scaleId, visibleRange)) {
      pinnedPriceScaleRanges[scaleId] = visibleRange;
      return {
        autoScale: false,
        visibleRange: {
          from: visibleRange.from,
          to: visibleRange.to,
        },
      };
    }
    pinnedPriceScaleRanges[scaleId] = null;
    return { autoScale: true, visibleRange: null };
  }

  function captureTimeScaleState() {
    const timeScale = priceChart.timeScale();
    const visibleLogicalRange = timeScale.getVisibleLogicalRange();
    let visibleTimeRange = null;
    try {
      const timeRange = timeScale.getVisibleRange();
      if (isValidTimeRange(timeRange)) {
        visibleTimeRange = { from: timeRange.from, to: timeRange.to };
      }
    } catch (_err) {
      visibleTimeRange = null;
    }
    return {
      visibleLogicalRange: isValidLogicalRange(visibleLogicalRange)
        ? { from: visibleLogicalRange.from, to: visibleLogicalRange.to }
        : null,
      visibleTimeRange: visibleTimeRange,
    };
  }

  function captureChartLayout() {
    if (!priceChart) return null;
    const priceScales = {};
    LAYOUT_PRICE_SCALE_IDS.forEach(function (scaleId) {
      priceScales[scaleId] = capturePriceScaleState(scaleId);
    });
    const timeScaleState = captureTimeScaleState();
    const hasPersistablePricePin = LAYOUT_PRICE_SCALE_IDS.some(function (scaleId) {
      const saved = priceScales[scaleId];
      return (
        saved &&
        saved.autoScale === false &&
        isPersistablePriceRange(scaleId, saved.visibleRange)
      );
    });
    if (
      !isValidLogicalRange(timeScaleState.visibleLogicalRange) &&
      !isValidTimeRange(timeScaleState.visibleTimeRange) &&
      !hasPersistablePricePin
    ) {
      return null;
    }
    return {
      v: 1,
      timeScale: timeScaleState,
      priceScales: priceScales,
    };
  }

  function applyPriceScalesFromLayout(layout) {
    if (!priceChart || !layout || layout.v !== 1) return;
    const priceScales = layout.priceScales || {};
    LAYOUT_PRICE_SCALE_IDS.forEach(function (scaleId) {
      const saved = priceScales[scaleId];
      if (!saved) return;
      const scale = priceChart.priceScale(scaleId);
      const scaleOpts = scale.options();
      const hasPinnedRange =
        saved.autoScale === false &&
        isPersistablePriceRange(scaleId, saved.visibleRange, layout);
      if (scaleId === "left" && scaleOpts.visible === false) {
        pinnedPriceScaleRanges.left = hasPinnedRange ? saved.visibleRange : null;
        return;
      }
      if (hasPinnedRange) {
        pinnedPriceScaleRanges[scaleId] = {
          from: saved.visibleRange.from,
          to: saved.visibleRange.to,
        };
        scale.applyOptions({ autoScale: true });
      } else {
        if (scaleId === "left") {
          pinnedPriceScaleRanges.left = null;
        } else {
          pinnedPriceScaleRanges[scaleId] = null;
        }
        scale.applyOptions({ autoScale: true });
      }
    });
    clearInvalidLeftPin(layout);
    clearInvalidRightPin(referencePriceFromLayout(layout));
    clearInvalidPmPin();
    refreshPinnedPriceScales();
  }

  function applyTimeScaleFromLayout(layout, mode) {
    if (!priceChart || !layout || layout.v !== 1) return false;
    const timeScale = priceChart.timeScale();
    const logicalRange = savedLayoutTimeRange(layout);
    const visibleTimeRange = savedLayoutVisibleTimeRange(layout);
    const restoreMode = mode || "auto";
    if (
      (restoreMode === "logical" || restoreMode === "auto") &&
      isValidLogicalRange(logicalRange)
    ) {
      timeScale.setVisibleLogicalRange({
        from: logicalRange.from,
        to: logicalRange.to,
      });
      return true;
    }
    if (
      (restoreMode === "time" || restoreMode === "auto") &&
      isValidTimeRange(visibleTimeRange)
    ) {
      timeScale.setVisibleRange({
        from: visibleTimeRange.from,
        to: visibleTimeRange.to,
      });
      return true;
    }
    return false;
  }

  function layoutTimeScaleMatches(layout) {
    if (!priceChart || !layout) return false;
    const timeScale = priceChart.timeScale();
    const logicalRange = savedLayoutTimeRange(layout);
    const visibleTimeRange = savedLayoutVisibleTimeRange(layout);
    let logicalMatch = false;
    const currentLogical = timeScale.getVisibleLogicalRange();
    if (isValidLogicalRange(logicalRange) && isValidLogicalRange(currentLogical)) {
      logicalMatch =
        Math.abs(currentLogical.from - logicalRange.from) < 1 &&
        Math.abs(currentLogical.to - logicalRange.to) < 1;
    }
    if (logicalMatch) return true;
    if (!isValidTimeRange(visibleTimeRange)) return false;
    try {
      const currentTime = timeScale.getVisibleRange();
      if (!isValidTimeRange(currentTime)) return false;
      const bucket = intervalBucketSeconds(chartStore.interval);
      return (
        Math.abs(Number(currentTime.from) - Number(visibleTimeRange.from)) <= bucket &&
        Math.abs(Number(currentTime.to) - Number(visibleTimeRange.to)) <= bucket
      );
    } catch (_err) {
      return false;
    }
  }

  function applyChartLayout(layout, timeScaleMode) {
    if (!priceChart || !layout || layout.v !== 1) return false;
    try {
      if (!applyTimeScaleFromLayout(layout, timeScaleMode)) {
        return false;
      }
      applyPriceScalesFromLayout(layout);
      return true;
    } catch (err) {
      console.warn("applyChartLayout failed:", err);
      return false;
    }
  }

  function scheduleChartLayoutRestore(savedLayout, hasOptions) {
    beginLayoutRestore();
    const generation = layoutRestoreGeneration;
    let attempt = 0;
    const finishRestore = function (_usedFitContent) {
      if (generation !== layoutRestoreGeneration) {
        return;
      }
      applyToggles();
      if (hasRestorableLayout(savedLayout)) {
        applyPriceScalesFromLayout(savedLayout);
        applyUserInteractedFlagsFromLayout(savedLayout);
      }
      endLayoutRestore();
      startLiveFeedsIfPending();
    };
    const runRestoreAttempt = function () {
      if (generation !== layoutRestoreGeneration) {
        return;
      }
      if (!hasRestorableLayout(savedLayout)) {
        resetPriceScales(hasOptions);
        if (seriesCache.futures.length) {
          priceChart.timeScale().fitContent();
        }
        finishRestore(true);
        return;
      }
      applyToggles();
      const timeScaleMode = attempt < 6 ? "logical" : "time";
      const ok = applyChartLayout(savedLayout, timeScaleMode);
      if (ok && layoutTimeScaleMatches(savedLayout)) {
        finishRestore(false);
        return;
      }
      attempt += 1;
      if (attempt < LAYOUT_RESTORE_MAX_ATTEMPTS) {
        requestAnimationFrame(runRestoreAttempt);
        return;
      }
      resetPriceScales(hasOptions);
      if (seriesCache.futures.length) {
        priceChart.timeScale().fitContent();
      }
      finishRestore(true);
    };
    requestAnimationFrame(function () {
      requestAnimationFrame(runRestoreAttempt);
    });
  }

  function persistChartLayout(base, interval) {
    const saveBase = typeof base === "string" ? base : chartStore.base;
    const saveInterval = typeof interval === "string" ? interval : chartStore.interval;
    syncPinnedPriceScalesFromViewport();
    const layout = captureChartLayout();
    if (!layout) return;
    writeChartLayout(
      saveBase,
      saveInterval,
      mergeCapturedPriceScales(layout, saveBase, saveInterval)
    );
  }

  function debouncedSaveLayout() {
    if (!shouldPersistLayout()) return;
    cancelPendingLayoutSave();
    layoutSaveTimer = setTimeout(function () {
      layoutSaveTimer = null;
      if (!shouldPersistLayout()) return;
      persistChartLayout();
    }, LAYOUT_SAVE_DEBOUNCE_MS);
  }

  function mergeCapturedPriceScales(layout, base, interval) {
    if (!layout || !layout.priceScales) return layout;
    const existing = readChartLayout(base, interval);
    if (!existing || !existing.priceScales) return layout;
    LAYOUT_PRICE_SCALE_IDS.forEach(function (scaleId) {
      const captured = layout.priceScales[scaleId];
      const previous = existing.priceScales[scaleId];
      if (
        captured &&
        !isValidPriceRange(captured.visibleRange) &&
        previous &&
        previous.autoScale === false &&
        isPersistablePriceRange(scaleId, previous.visibleRange, existing)
      ) {
        layout.priceScales[scaleId] = {
          autoScale: false,
          visibleRange: {
            from: previous.visibleRange.from,
            to: previous.visibleRange.to,
          },
        };
      }
    });
    return layout;
  }

  function flushSaveLayout(base, interval) {
    cancelPendingLayoutSave();
    persistChartLayout(base, interval);
  }

  function formatStrikeLabel(strike, fallbackLabel) {
    if (strike != null && Number.isFinite(Number(strike))) {
      return "$" + Number(strike).toLocaleString("en-US", { maximumFractionDigits: 2 });
    }
    return fallbackLabel || "—";
  }

  function renderPmStrikeLabels() {
    const container = document.getElementById("pm-strike-labels");
    if (!container) return;

    const items = [];
    pmSeriesMap.forEach(function (entry, marketId) {
      const points = seriesCache.pm[marketId] || [];
      if (!points.length) return;
      const meta = seriesMeta.get(entry.series);
      items.push({
        strike: entry.strike,
        label: formatStrikeLabel(entry.strike, entry.label),
        color: meta ? meta.color : pmSecondaryColor(items.length),
      });
    });

    items.sort(function (a, b) {
      if (a.strike == null && b.strike == null) return 0;
      if (a.strike == null) return 1;
      if (b.strike == null) return -1;
      return a.strike - b.strike;
    });

    container.innerHTML = items
      .map(function (item) {
        return (
          '<li class="pm-strike-label">' +
          '<span class="pm-strike-swatch" style="background:' +
          item.color +
          '"></span>' +
          '<span class="pm-strike-price">' +
          item.label +
          "</span></li>"
        );
      })
      .join("");
  }

  function removePmSeriesEntry(marketId) {
    const entry = pmSeriesMap.get(marketId);
    if (!entry || !priceChart) return;
    priceChart.removeSeries(entry.series);
    pmSeriesMap.delete(marketId);
    delete seriesCache.pm[marketId];
  }

  function clearPmOverlay() {
    Array.from(pmSeriesMap.keys()).forEach(function (marketId) {
      removePmSeriesEntry(marketId);
    });
    seriesCache.pm = {};
    chartStore.pmEventSlug = null;
    chartStore.pmEventUrl = null;
    renderPmStrikeLabels();
    applyPmPriceScale();
  }

  function removeOptionSeriesEntry(symbol) {
    const entry = optionSeriesMap.get(symbol);
    if (!entry || !priceChart) return;
    priceChart.removeSeries(entry.series);
    optionSeriesMap.delete(symbol);
    delete seriesCache.options[symbol];
  }

  function ensurePmSeries(item, color) {
    if (!priceChart) return null;
    const marketId = item.market_id;
    let entry = pmSeriesMap.get(marketId);
    const strikeLabel = formatStrikeLabel(item.strike, item.label);
    const lineColor = color || pmSecondaryColor(0);

    if (entry) {
      entry.label = strikeLabel;
      entry.strike = item.strike;
      entry.series.applyOptions({
        color: lineColor,
        title: strikeLabel,
        autoscaleInfoProvider: pmAutoscaleInfo,
      });
      registerSeriesMeta(entry.series, {
        name: strikeLabel,
        type: "line",
        color: lineColor,
        suffix: "%",
        strike: item.strike,
      });
      return entry;
    }

    const series = priceChart.addLineSeries({
      color: lineColor,
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      priceScaleId: "pm",
      title: strikeLabel,
      lastValueVisible: true,
      priceLineVisible: false,
      autoscaleInfoProvider: pmAutoscaleInfo,
    });
    registerSeriesMeta(series, {
      name: strikeLabel,
      type: "line",
      color: lineColor,
      suffix: "%",
      strike: item.strike,
    });
    entry = {
      series: series,
      label: strikeLabel,
      strike: item.strike,
    };
    pmSeriesMap.set(marketId, entry);
    if (!seriesCache.pm[marketId]) {
      seriesCache.pm[marketId] = [];
    }
    return entry;
  }

  function ensureOptionSeries(item, index) {
    if (!priceChart) return null;
    const symbol = item.symbol;
    let entry = optionSeriesMap.get(symbol);
    const label = item.label || formatStrikeLabel(item.strike, symbol);
    const color = optionColor(item.option_type, index);

    if (entry) {
      entry.label = label;
      entry.strike = item.strike;
      entry.option_type = item.option_type;
      entry.series.applyOptions({
        color: color,
        title: label,
        autoscaleInfoProvider: pinnedAutoscaleInfo("left"),
      });
      registerSeriesMeta(entry.series, {
        name: label,
        type: "line",
        color: color,
        strike: item.strike,
      });
      return entry;
    }

    const series = priceChart.addLineSeries({
      color: color,
      lineWidth: 2,
      priceScaleId: "left",
      title: label,
      lastValueVisible: false,
      priceLineVisible: false,
      autoscaleInfoProvider: pinnedAutoscaleInfo("left"),
    });
    registerSeriesMeta(series, {
      name: label,
      type: "line",
      color: color,
      strike: item.strike,
    });
    entry = {
      series: series,
      label: label,
      strike: item.strike,
      option_type: item.option_type,
    };
    optionSeriesMap.set(symbol, entry);
    seriesCache.options[symbol] = [];
    return entry;
  }

  function setupResize(pricesEl) {
    const ro = new ResizeObserver(function () {
      if (priceChart && pricesEl) {
        priceChart.applyOptions({
          width: pricesEl.clientWidth,
          height: pricesEl.clientHeight,
        });
      }
    });
    ro.observe(pricesEl);
  }

  async function fetchBatch(params) {
    const qs = new URLSearchParams(params);
    const resp = await fetch("/api/chart/batch?" + qs.toString(), {
      credentials: "same-origin",
    });
    if (!resp.ok) throw new Error("batch fetch failed: " + resp.status);
    return resp.json();
  }

  async function fetchOptionsChain(base) {
    const resp = await fetch("/api/options/chain?base=" + encodeURIComponent(base), {
      credentials: "same-origin",
    });
    if (!resp.ok) throw new Error("options chain fetch failed: " + resp.status);
    return resp.json();
  }

  function pmStorageKey(base) {
    return STORAGE_PM_EVENT + base;
  }

  function loadStoredPmEvent(base) {
    try {
      return sessionStorage.getItem(pmStorageKey(base)) || null;
    } catch (_err) {
      return null;
    }
  }

  function saveSelectedPmEvent(base, slug) {
    if (slug) {
      sessionStorage.setItem(pmStorageKey(base), slug);
    } else {
      sessionStorage.removeItem(pmStorageKey(base));
    }
    chartStore.pmEventSlug = slug || null;
  }

  async function fetchPmEvents(base) {
    const resp = await fetch("/api/polymarket/events?base=" + encodeURIComponent(base), {
      credentials: "same-origin",
    });
    if (!resp.ok) return { events: [], max_events: 10 };
    return resp.json();
  }

  async function importPmEvents(base, urlsText) {
    const resp = await fetch("/api/polymarket/events/import", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base: base, urls_text: urlsText }),
    });
    if (!resp.ok) {
      let detail = "Failed to import Polymarket URLs";
      try {
        const err = await resp.json();
        if (typeof err.detail === "string") {
          detail = err.detail;
        } else if (Array.isArray(err.detail)) {
          detail = err.detail.map(function (d) {
            return d.msg || String(d);
          }).join("; ");
        }
      } catch (_parseErr) {
        detail = "Failed to import Polymarket URLs";
      }
      throw new Error(detail);
    }
    return resp.json();
  }

  function formatPmCountdown(endDateIso) {
    if (!endDateIso) return "";
    const endMs = Date.parse(endDateIso);
    if (Number.isNaN(endMs)) return "";
    let totalSec = Math.max(0, Math.floor((endMs - Date.now()) / 1000));
    const day = Math.floor(totalSec / 86400);
    totalSec %= 86400;
    const hr = Math.floor(totalSec / 3600);
    totalSec %= 3600;
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    return day + "д " + hr + "ч " + min + "м " + sec + "с";
  }

  function stopPmCountdown() {
    if (pmCountdownTimer) {
      clearInterval(pmCountdownTimer);
      pmCountdownTimer = null;
    }
  }

  function updatePmCountdownDisplay() {
    const el = document.getElementById("pm-expiry-countdown");
    if (!el) return;
    if (!chartStore.pmEventEndDate) {
      el.textContent = "";
      el.classList.add("hidden");
      return;
    }
    el.textContent = formatPmCountdown(chartStore.pmEventEndDate);
    el.classList.remove("hidden");
    if (Date.parse(chartStore.pmEventEndDate) <= Date.now()) {
      stopPmCountdown();
    }
  }

  function startPmCountdown(endDate) {
    stopPmCountdown();
    chartStore.pmEventEndDate = endDate || null;
    updatePmCountdownDisplay();
    if (!endDate || Number.isNaN(Date.parse(endDate))) return;
    if (Date.parse(endDate) <= Date.now()) return;
    pmCountdownTimer = setInterval(updatePmCountdownDisplay, 1000);
  }

  function resolvePmSelection(events, base) {
    const slugs = (events || []).map(function (ev) {
      return ev.event_slug;
    });
    const stored = loadStoredPmEvent(base);
    if (stored && slugs.indexOf(stored) >= 0) {
      return stored;
    }
    return slugs.length ? slugs[0] : null;
  }

  function findPmEvent(events, slug) {
    if (!slug) return null;
    return (events || []).find(function (ev) {
      return ev.event_slug === slug;
    }) || null;
  }

  function applyPmSelectionFromEvents(events, base) {
    const slug = resolvePmSelection(events, base);
    saveSelectedPmEvent(base, slug);
    const selected = findPmEvent(events, slug);
    chartStore.pmEventUrl = selected ? selected.event_url : null;
    chartStore.pmEventEndDate = selected ? selected.event_end_date : null;
    if (!slug) {
      clearPmOverlay();
    }
    startPmCountdown(chartStore.pmEventEndDate);
    return slug;
  }

  function renderPmEventsList(base) {
    const listEl = document.getElementById("pm-events-list");
    if (!listEl) return;
    const events = chartStore.pmEvents || [];
    const selectedSlug = chartStore.pmEventSlug;
    const radioName = "pm-event-" + base;
    if (!events.length) {
      listEl.innerHTML = '<div class="pm-event-meta">No events imported</div>';
      return;
    }
    listEl.innerHTML = events
      .map(function (ev) {
        const checked = ev.event_slug === selectedSlug ? " checked" : "";
        const title = ev.event_title || ev.event_slug;
        const expiry = ev.event_end_date
          ? "Ends: " + new Date(ev.event_end_date).toLocaleString()
          : "No expiry";
        return (
          '<label class="pm-event-row">' +
          '<input type="radio" name="' +
          radioName +
          '" value="' +
          ev.event_slug +
          '"' +
          checked +
          ">" +
          '<span class="pm-event-title">' +
          title +
          "</span>" +
          '<span class="pm-event-meta">' +
          expiry +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function allChainSymbols(chain) {
    const symbols = [];
    (chain.calls || []).forEach(function (c) {
      symbols.push(c.symbol);
    });
    (chain.puts || []).forEach(function (p) {
      symbols.push(p.symbol);
    });
    return symbols;
  }

  function pickDefaultSymbols(chain) {
    const calls = (chain.calls || []).filter(function (c) {
      return c.otm;
    });
    const puts = (chain.puts || []).filter(function (p) {
      return p.otm;
    });
    let defaultCall = null;
    let defaultPut = null;
    if (calls.length) {
      defaultCall = calls.reduce(function (best, c) {
        return !best || c.strike < best.strike ? c : best;
      }, null);
    } else if (chain.calls && chain.calls.length && chain.spot != null) {
      defaultCall = chain.calls.reduce(function (best, c) {
        const dist = Math.abs(c.strike - chain.spot);
        const bestDist = best ? Math.abs(best.strike - chain.spot) : Infinity;
        return dist < bestDist ? c : best;
      }, null);
    }
    if (puts.length) {
      defaultPut = puts.reduce(function (best, p) {
        return !best || p.strike > best.strike ? p : best;
      }, null);
    } else if (chain.puts && chain.puts.length && chain.spot != null) {
      defaultPut = chain.puts.reduce(function (best, p) {
        const dist = Math.abs(p.strike - chain.spot);
        const bestDist = best ? Math.abs(best.strike - chain.spot) : Infinity;
        return dist < bestDist ? p : best;
      }, null);
    }
    const out = [];
    if (defaultCall) out.push(defaultCall.symbol);
    if (defaultPut) out.push(defaultPut.symbol);
    return out;
  }

  function loadStoredSymbols(base) {
    try {
      const raw = sessionStorage.getItem(optionStorageKey(base));
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
    } catch (_err) {
      return [];
    }
  }

  function saveSelectedSymbols(base, symbols) {
    sessionStorage.setItem(optionStorageKey(base), JSON.stringify(symbols));
    chartStore.selectedOptionSymbols = symbols;
  }

  function saveSelectedExpiry(base, expiry) {
    if (expiry) {
      sessionStorage.setItem(optionExpiryStorageKey(base), expiry);
    } else {
      sessionStorage.removeItem(optionExpiryStorageKey(base));
    }
    chartStore.optionsExpiry = expiry;
  }

  function renderOptionsDropdown(chain) {
    const callsEl = document.getElementById("options-calls-list");
    const putsEl = document.getElementById("options-puts-list");
    const expiryEl = document.getElementById("options-expiry-label");
    if (!callsEl || !putsEl) return;

    if (expiryEl) {
      expiryEl.textContent = chain.expiry_label
        ? "Expiry: " + chain.expiry_label
        : "No options chain";
    }

    const selected = new Set(chartStore.selectedOptionSymbols);

    function renderCol(container, title, items, optionType) {
      const rows = (items || [])
        .map(function (item) {
          const checked = selected.has(item.symbol) ? " checked" : "";
          const otmClass = item.otm ? " otm" : "";
          const strikeLabel = formatStrikeLabel(item.strike, String(item.strike));
          const ask =
            item.ask_price != null ? Number(item.ask_price).toFixed(2) : "—";
          return (
            '<label class="options-row' +
            otmClass +
            '" data-symbol="' +
            item.symbol +
            '">' +
            '<input type="checkbox" data-option-type="' +
            optionType +
            '" value="' +
            item.symbol +
            '"' +
            checked +
            ">" +
            '<span class="options-row-strike">' +
            strikeLabel +
            "</span>" +
            '<span class="options-row-ask">' +
            ask +
            "</span>" +
            "</label>"
          );
        })
        .join("");
      container.innerHTML =
        '<div class="options-col-title">' + title + "</div>" + rows;
    }

    renderCol(callsEl, "Calls", chain.calls || [], "call");
    renderCol(putsEl, "Puts", chain.puts || [], "put");
  }

  async function syncOptionsChain(base) {
    const chain = await fetchOptionsChain(base);
    chartStore.optionsChain = chain;

    const storedExpiry = sessionStorage.getItem(optionExpiryStorageKey(base));
    const expiryChanged =
      chain.expiry && storedExpiry && chain.expiry !== storedExpiry;

    let symbols = loadStoredSymbols(base);
    const validSymbols = new Set(allChainSymbols(chain));

    if (expiryChanged) {
      symbols = [];
      sessionStorage.removeItem(optionStorageKey(base));
    }

    symbols = symbols.filter(function (s) {
      return validSymbols.has(s);
    });

    if (!symbols.length) {
      symbols = pickDefaultSymbols(chain);
    }

    saveSelectedSymbols(base, symbols);
    saveSelectedExpiry(base, chain.expiry);

    optionSeriesMap.forEach(function (_entry, symbol) {
      if (!validSymbols.has(symbol)) {
        removeOptionSeriesEntry(symbol);
      }
    });

    renderOptionsDropdown(chain);
    return chain;
  }

  function updateLegend(data) {
    const el = document.getElementById("legend");
    const parts = [chartStore.base];
    const options = data.options || {};
    const optCount = (options.series || []).length;
    if (optCount) {
      const expiryPart = options.expiry
        ? chartStore.optionsChain && chartStore.optionsChain.expiry_label
          ? chartStore.optionsChain.expiry_label
          : options.expiry
        : "";
      parts.push("Options: " + optCount + " series" + (expiryPart ? " | " + expiryPart : ""));
    } else if (chartStore.optionsChain && chartStore.optionsChain.expiry) {
      parts.push("Options: select strikes");
    } else {
      parts.push("Options: no chain");
    }
    const pm = data.polymarket || {};
    if (pm.event_slug) {
      parts.push("PM event: " + pm.event_slug);
    }
    const series = pm.series || [];
    if (series.length) {
      parts.push("PM strikes: " + series.length);
    } else if (pm.event_slug) {
      parts.push("Polymarket: awaiting ingest");
    } else {
      parts.push("Polymarket: paste event URL");
    }
    el.textContent = parts.join(" | ");
  }

  function mergeByTime(existing, newPoints) {
    const map = new Map();
    (existing || []).forEach(function (p) {
      map.set(p.time, p);
    });
    newPoints.forEach(function (p) {
      map.set(p.time, p);
    });
    return Array.from(map.values()).sort(function (a, b) {
      return a.time - b.time;
    });
  }

  function applyPmSeriesData(pmPayload, prepend) {
    const seriesList = (pmPayload && pmPayload.series) || [];
    chartStore.pmEventSlug = pmPayload ? pmPayload.event_slug : null;
    chartStore.pmEventUrl = pmPayload ? pmPayload.event_url : null;

    const activeIds = new Set();
    seriesList.forEach(function (item) {
      const marketId = item.market_id;
      if (!marketId) return;
      activeIds.add(marketId);
      const points = item.points || [];
      if (prepend) {
        seriesCache.pm[marketId] = mergeByTime(seriesCache.pm[marketId], points);
      } else {
        seriesCache.pm[marketId] = points;
      }
    });

    applyPmSeriesColors(seriesList);

    seriesList.forEach(function (item) {
      const marketId = item.market_id;
      if (!marketId) return;
      const entry = pmSeriesMap.get(marketId);
      if (!entry) return;
      entry.series.setData(seriesCache.pm[marketId]);
    });

    pmSeriesMap.forEach(function (_entry, marketId) {
      if (!activeIds.has(marketId)) {
        removePmSeriesEntry(marketId);
      }
    });

    applyPmPriceScale(hasSavedLayoutForCurrent() || layoutRestoring);
    renderPmStrikeLabels();
    return seriesList;
  }

  function applyOptionSeriesData(optionsPayload, prepend) {
    const seriesList = (optionsPayload && optionsPayload.series) || [];
    const activeSymbols = new Set();
    let callIndex = 0;
    let putIndex = 0;

    seriesList.forEach(function (item) {
      const symbol = item.symbol;
      if (!symbol) return;
      activeSymbols.add(symbol);
      const idx = item.option_type === "put" ? putIndex++ : callIndex++;
      const entry = ensureOptionSeries(item, idx);
      if (!entry) return;
      const points = item.points || [];
      if (prepend) {
        seriesCache.options[symbol] = mergeByTime(seriesCache.options[symbol], points);
      } else {
        seriesCache.options[symbol] = points;
      }
      entry.series.setData(seriesCache.options[symbol]);
    });

    optionSeriesMap.forEach(function (_entry, symbol) {
      if (!activeSymbols.has(symbol)) {
        removeOptionSeriesEntry(symbol);
      }
    });

    return seriesList;
  }

  function hasOptionData() {
    return Object.keys(seriesCache.options).some(function (sym) {
      return seriesCache.options[sym] && seriesCache.options[sym].length > 0;
    });
  }

  function updateNewestTimeFromCache() {
    const futures = seriesCache.futures;
    chartStore.newestTime = futures.length ? futures[futures.length - 1].time : null;
  }

  function restoreOrFitChartLayout(hasOptions) {
    const savedLayout = readChartLayout(chartStore.base, chartStore.interval);
    if (hasRestorableLayout(savedLayout)) {
      scheduleChartLayoutRestore(savedLayout, hasOptions);
      return;
    }
    resetPriceScales(hasOptions);
    if (seriesCache.futures.length) {
      priceChart.timeScale().fitContent();
    }
    applyToggles();
    startLiveFeedsIfPending();
  }

  function applyBatchData(data, prepend) {
    const candles = data.futures.candles || [];

    if (prepend) {
      const prevFuturesLen = seriesCache.futures.length;
      seriesCache.futures = mergeByTime(seriesCache.futures, candles);
      applyOptionSeriesData(data.options, true);
      applyPmSeriesData(data.polymarket, true);
      if (seriesCache.futures.length === prevFuturesLen) {
        chartStore.hasMore = false;
      }
    } else {
      seriesCache.futures = candles;
      applyOptionSeriesData(data.options, false);
      applyPmSeriesData(data.polymarket, false);
      chartStore.hasMore = Boolean(data.futures && data.futures.has_more);
      if (candles.length) {
        chartStore.oldestTime = candles[0].time;
      }
      updateNewestTimeFromCache();
    }

    futuresSeries.setData(seriesCache.futures);
    const hasOptions = hasOptionData();
    clearInvalidLeftPin();
    clearInvalidPmPin();

    if (!prepend) {
      const savedLayout = readChartLayout(chartStore.base, chartStore.interval);
      const shouldRestoreLayout = hasRestorableLayout(savedLayout);
      if (shouldRestoreLayout) {
        scheduleChartLayoutRestore(savedLayout, hasOptions);
      } else {
        restoreOrFitChartLayout(hasOptions);
      }
    } else {
      priceChart.priceScale("left").applyOptions({
        visible: hasOptions && isOptionsOverlayEnabled(),
      });
      applyToggles();
    }

    updateLegend(data);
  }

  function intervalBucketSeconds(interval) {
    return INTERVAL_SECONDS[interval] || INTERVAL_SECONDS["5m"];
  }

  function pollIntervalMs(interval) {
    return POLL_INTERVAL_MS[interval] || POLL_INTERVAL_MS["5m"];
  }

  function stopFuturesSSE() {
    if (futuresEventSource) {
      futuresEventSource.close();
      futuresEventSource = null;
    }
  }

  function startFuturesSSE() {
    stopFuturesSSE();
    if (document.hidden) return;
    const qs = new URLSearchParams({
      base: chartStore.base,
      interval: chartStore.interval,
    });
    futuresEventSource = new EventSource("/api/chart/stream?" + qs.toString());
    futuresEventSource.onmessage = function (event) {
      if (!event.data || event.data.indexOf("{") !== 0) return;
      try {
        const payload = JSON.parse(event.data);
        if (payload.type !== "kline") return;
        if (payload.base !== chartStore.base || payload.interval !== chartStore.interval) {
          return;
        }
        applyFuturesSseUpdate(payload.candle, Boolean(payload.confirmed));
      } catch (err) {
        console.error("futures SSE parse error:", err);
      }
    };
  }

  function applyFuturesSseUpdate(candle, confirmed) {
    if (!futuresSeries || !candle || candle.time == null) return;
    const bar = {
      time: candle.time,
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close),
    };
    const prevLastTime = seriesCache.futures.length
      ? seriesCache.futures[seriesCache.futures.length - 1].time
      : null;
    seriesCache.futures = mergeByTime(seriesCache.futures, [bar]);
    const lastBar = seriesCache.futures[seriesCache.futures.length - 1];
    if (prevLastTime === lastBar.time) {
      futuresSeries.update(lastBar);
    } else {
      futuresSeries.setData(seriesCache.futures);
    }
    updateNewestTimeFromCache();
    if (confirmed) {
      chartStore.hasMore = false;
    }
    refreshPinnedPriceScalesIfNeeded();
  }

  function stopLivePolling() {
    if (livePollTimer) {
      clearInterval(livePollTimer);
      livePollTimer = null;
    }
  }

  function startLivePolling() {
    stopLivePolling();
    if (document.hidden) return;
    livePollTimer = setInterval(livePollTick, pollIntervalMs(chartStore.interval));
  }

  async function livePollTick(catchUp) {
    if (document.hidden || chartStore.loading) return;
    await pollLiveUpdate(Boolean(catchUp));
  }

  function applyLineSeriesLiveUpdate(entry, existingPoints, newPoints) {
    const prevLastTime = existingPoints.length
      ? existingPoints[existingPoints.length - 1].time
      : null;
    const merged = mergeByTime(existingPoints, newPoints);
    if (!merged.length) {
      return merged;
    }
    const lastPoint = merged[merged.length - 1];
    if (prevLastTime === lastPoint.time) {
      entry.series.update(lastPoint);
    } else {
      entry.series.setData(merged);
    }
    return merged;
  }

  function applyLiveUpdate(data) {
    const hasOptions = Boolean(data.options && data.options.series && data.options.series.length);
    const hasPm = Boolean(
      data.polymarket && data.polymarket.series && data.polymarket.series.length
    );
    if (!hasOptions && !hasPm) return;

    const optionsSeries = (data.options && data.options.series) || [];
    let callIndex = 0;
    let putIndex = 0;
    optionsSeries.forEach(function (item) {
      const symbol = item.symbol;
      const points = item.points || [];
      if (!symbol || !points.length) return;
      const idx = item.option_type === "put" ? putIndex++ : callIndex++;
      const entry = ensureOptionSeries(item, idx);
      if (!entry) return;
      seriesCache.options[symbol] = applyLineSeriesLiveUpdate(
        entry,
        seriesCache.options[symbol] || [],
        points
      );
    });

    const pmPayload = data.polymarket || {};
    const pmSeries = pmPayload.series || [];
    chartStore.pmEventSlug = pmPayload.event_slug || null;
    chartStore.pmEventUrl = pmPayload.event_url || null;
    if (!chartStore.pmEventSlug && !pmSeries.length) {
      clearPmOverlay();
      updateLegend(data);
      return;
    }
    const pmActive = [];
    pmSeries.forEach(function (item) {
      const marketId = item.market_id;
      const points = item.points || [];
      if (!marketId || !points.length) return;
      let entry = pmSeriesMap.get(marketId);
      if (!entry) {
        entry = ensurePmSeries(item, pmSecondaryColor(0));
      }
      if (!entry) return;
      seriesCache.pm[marketId] = applyLineSeriesLiveUpdate(
        entry,
        seriesCache.pm[marketId] || [],
        points
      );
      pmActive.push(item);
    });

    if (hasPm) {
      applyPmSeriesColors(pmActive);
      applyPmPriceScale(true);
      renderPmStrikeLabels();
    }

    refreshPinnedPriceScalesIfNeeded();
    updateLegend(data);
  }

  async function pollLiveUpdate(catchUp) {
    if (chartStore.loading || document.hidden || pollInFlight) return;
    if (chartStore.newestTime == null) return;

    pollInFlight = true;
    const bucketSec = intervalBucketSeconds(chartStore.interval);
    const lookbackBuckets = catchUp ? LIVE_UPDATE_LIMIT : 1;
    const params = {
      base: chartStore.base,
      interval: chartStore.interval,
      from: String(chartStore.newestTime - bucketSec * lookbackBuckets),
      limit: String(LIVE_UPDATE_LIMIT),
    };
    if (chartStore.selectedOptionSymbols.length) {
      params.symbols = chartStore.selectedOptionSymbols.join(",");
    }
    if (chartStore.pmEventSlug) {
      params.pm_event_slug = chartStore.pmEventSlug;
    }

    try {
      const data = await fetchBatch(params);
      applyLiveUpdate(data);
    } catch (err) {
      console.error("pollLiveUpdate failed:", err);
    } finally {
      pollInFlight = false;
    }
  }

  function setupVisibilityListener() {
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        flushSaveLayout();
        stopLivePolling();
        stopFuturesSSE();
        return;
      }
      if (layoutRestoring || chartStore.loading) {
        requestLiveFeedsAfterLayout();
        return;
      }
      startFuturesSSE();
      startLivePolling();
      livePollTick(true);
    });
  }

  async function loadChart(reset) {
    if (chartStore.loading) {
      if (reset) {
        chartStore.pendingReload = true;
      }
      return;
    }
    if (!reset && !chartStore.hasMore) return;
    if (reset) {
      stopLivePolling();
      stopFuturesSSE();
      cancelPendingLayoutSave();
      layoutRestoreGeneration += 1;
      clearPinnedPriceScaleRanges();
      leftScaleUserInteracted = false;
      rightScaleUserInteracted = false;
    }
    chartStore.loading = true;
    let loadSucceeded = false;
    try {
      if (reset) {
        await syncOptionsChain(chartStore.base);
      }
      const params = {
        base: chartStore.base,
        interval: chartStore.interval,
        limit: String(BATCH_LIMIT),
      };
      if (chartStore.selectedOptionSymbols.length) {
        params.symbols = chartStore.selectedOptionSymbols.join(",");
      }
      if (chartStore.pmEventSlug) {
        params.pm_event_slug = chartStore.pmEventSlug;
      }
      if (!reset && chartStore.oldestTime) {
        params.to = String(chartStore.oldestTime - 1);
      }
      const prepend = !reset && chartStore.oldestTime != null;
      const data = await fetchBatch(params);
      applyBatchData(data, prepend);
      if (prepend && data.futures.candles.length) {
        chartStore.oldestTime = data.futures.candles[0].time;
      }
      if (!data.futures.has_more) {
        chartStore.hasMore = false;
      }
      loadSucceeded = true;
    } catch (err) {
      console.error(err);
      document.getElementById("legend").textContent = "Error loading chart data";
    } finally {
      chartStore.loading = false;
      if (chartStore.pendingReload) {
        chartStore.pendingReload = false;
        void loadChart(true);
        return;
      }
      if (reset && loadSucceeded) {
        requestLiveFeedsAfterLayout();
      }
    }
  }

  async function loadPmEventsForBase(base) {
    try {
      const data = await fetchPmEvents(base);
      chartStore.pmEvents = data.events || [];
      applyPmSelectionFromEvents(chartStore.pmEvents, base);
      renderPmEventsList(base);
      updateLegend({
        options: { series: [] },
        polymarket: {
          event_slug: chartStore.pmEventSlug,
          event_url: chartStore.pmEventUrl,
          series: [],
        },
      });
    } catch (_err) {
      chartStore.pmEvents = [];
      applyPmSelectionFromEvents([], base);
      renderPmEventsList(base);
      clearPmOverlay();
      startPmCountdown(null);
    }
  }

  function setupInfiniteScroll() {
    // Prepend trigger is registered together with layout save in setupLayoutPersistence().
  }

  function setupLayoutPersistence() {
    if (!priceChart) return;
    priceChart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (shouldPersistLayout() && isValidLogicalRange(range)) {
        debouncedSaveLayout();
      }
      if (!range || chartStore.loading || layoutRestoring || !chartStore.hasMore) return;
      if (range.from < 5) {
        loadChart(false);
      }
    });
    const pricesEl = document.getElementById("chart-prices");
    if (pricesEl) {
      function priceScaleAtPointer(event) {
        if (!priceChart) return null;
        const leftWidth = priceChart.priceScale("left").width();
        const rightWidth = priceChart.priceScale("right").width();
        const chartWidth = pricesEl.clientWidth;
        const x = event.offsetX;
        if (leftWidth > 0 && x <= leftWidth) {
          return "left";
        }
        if (rightWidth > 0 && x >= chartWidth - rightWidth) {
          return "right";
        }
        return null;
      }
      pricesEl.addEventListener("pointerdown", function (event) {
        const scaleId = priceScaleAtPointer(event);
        if (scaleId === "left") {
          leftScaleUserInteracted = true;
        } else if (scaleId === "right") {
          rightScaleUserInteracted = true;
        }
      });
      pricesEl.addEventListener("pointerup", function () {
        if (shouldPersistLayout()) {
          scheduleSyncPinnedAndSave();
        }
      });
      pricesEl.addEventListener(
        "wheel",
        function (event) {
          const scaleId = priceScaleAtPointer(event);
          if (scaleId === "left") {
            leftScaleUserInteracted = true;
          } else if (scaleId === "right") {
            rightScaleUserInteracted = true;
          }
          if (shouldPersistLayout()) {
            scheduleSyncPinnedAndSave();
          }
        },
        { passive: true }
      );
    }
    window.addEventListener("pagehide", function () {
      flushSaveLayout();
    });
  }

  function getActiveSeriesList() {
    const list = [futuresSeries];
    optionSeriesMap.forEach(function (entry) {
      list.push(entry.series);
    });
    pmSeriesMap.forEach(function (entry) {
      list.push(entry.series);
    });
    return list;
  }

  function setupCrosshairTooltip() {
    if (!priceChart) return;
    const tooltip = document.getElementById("chart-tooltip");
    const container = document.querySelector(".chart-container");

    function renderTooltip(param, chartEl, activeSeriesList) {
      if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
        tooltip.classList.add("hidden");
        tooltip.setAttribute("aria-hidden", "true");
        return;
      }

      const rows = [];
      activeSeriesList.forEach(function (series) {
        const meta = seriesMeta.get(series);
        if (!meta) return;
        const dataPoint = param.seriesData.get(series);
        const value = formatSeriesValue(meta, dataPoint);
        if (value == null) return;
        const displayName =
          meta.strike != null && meta.suffix
            ? formatStrikeLabel(meta.strike, meta.name) + " Yes"
            : meta.name;
        rows.push({
          name: displayName,
          value: value + (meta.suffix || ""),
          color: meta.color,
        });
      });

      if (!rows.length) {
        tooltip.classList.add("hidden");
        tooltip.setAttribute("aria-hidden", "true");
        return;
      }

      const timeLabel = new Date(param.time * 1000).toLocaleString();
      let html = '<div class="chart-tooltip-row"><span class="chart-tooltip-name">' + timeLabel + "</span></div>";
      rows.forEach(function (row) {
        html +=
          '<div class="chart-tooltip-row">' +
          '<span class="chart-tooltip-name" style="color:' +
          row.color +
          '">' +
          row.name +
          "</span>" +
          '<span class="chart-tooltip-value">' +
          row.value +
          "</span></div>";
      });
      tooltip.innerHTML = html;
      tooltip.classList.remove("hidden");
      tooltip.setAttribute("aria-hidden", "false");

      const rect = chartEl.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      const pad = 8;
      const cursorX = rect.left - containerRect.left + param.point.x;
      const cursorY = rect.top - containerRect.top + param.point.y;
      const tooltipWidth = tooltip.offsetWidth;
      const tooltipHeight = tooltip.offsetHeight;

      let x = cursorX + 14;
      if (x + tooltipWidth > container.clientWidth - pad) {
        x = cursorX - tooltipWidth - 14;
      }
      x = Math.max(pad, Math.min(x, container.clientWidth - tooltipWidth - pad));

      let y = cursorY - 10;
      if (y + tooltipHeight > container.clientHeight - pad) {
        y = cursorY - tooltipHeight - 10;
      }
      y = Math.max(pad, Math.min(y, container.clientHeight - tooltipHeight - pad));

      tooltip.style.left = x + "px";
      tooltip.style.top = y + "px";
    }

    priceChart.subscribeCrosshairMove(function (param) {
      renderTooltip(param, document.getElementById("chart-prices"), getActiveSeriesList());
    });
  }

  async function changeChartBase(base) {
    if (!base || base === chartStore.base) {
      return;
    }
    const prevBase = chartStore.base;
    const prevInterval = chartStore.interval;
    cancelPendingLayoutSave();
    try {
      flushSaveLayout(prevBase, prevInterval);
    } catch (err) {
      console.error("flushSaveLayout before base change failed:", err);
    }
    layoutSwitchInProgress = true;
    chartStore.base = base;
    chartStore.oldestTime = null;
    chartStore.newestTime = null;
    chartStore.hasMore = true;
    sessionStorage.setItem(STORAGE_BASE, base);
    document.querySelectorAll("#asset-tabs button").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.base === base);
    });
    try {
      clearPmOverlay();
      await loadPmEventsForBase(base);
      await loadChart(true);
    } catch (err) {
      console.error("changeChartBase load failed:", err);
      document.getElementById("legend").textContent = "Error loading chart data";
    } finally {
      layoutSwitchInProgress = false;
    }
  }

  async function changeChartInterval(interval) {
    if (!interval || interval === chartStore.interval) {
      return;
    }
    const prevBase = chartStore.base;
    const prevInterval = chartStore.interval;
    cancelPendingLayoutSave();
    try {
      flushSaveLayout(prevBase, prevInterval);
    } catch (err) {
      console.error("flushSaveLayout before interval change failed:", err);
    }
    layoutSwitchInProgress = true;
    chartStore.interval = interval;
    chartStore.oldestTime = null;
    chartStore.newestTime = null;
    chartStore.hasMore = true;
    sessionStorage.setItem(STORAGE_INTERVAL, interval);
    document.querySelectorAll("#tf-tabs button").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.interval === interval);
    });
    try {
      await loadChart(true);
    } catch (err) {
      console.error("changeChartInterval load failed:", err);
      document.getElementById("legend").textContent = "Error loading chart data";
    } finally {
      layoutSwitchInProgress = false;
    }
  }

  function applyToggles() {
    clearInvalidLeftPin();
    clearInvalidPmPin();
    futuresSeries.applyOptions({
      visible: document.getElementById("toggle-futures").checked,
    });
    const optionsChecked = isOptionsOverlayEnabled();
    optionSeriesMap.forEach(function (entry, symbol) {
      const pointsLen = seriesCache.options[symbol] ? seriesCache.options[symbol].length : 0;
      entry.series.applyOptions({
        visible: optionsChecked && pointsLen > 0,
      });
    });
    if (priceChart) {
      priceChart.priceScale("left").applyOptions({
        visible: optionsChecked && hasOptionData(),
      });
    }
    const pmChecked = document.getElementById("toggle-pm").checked;
    pmSeriesMap.forEach(function (entry, marketId) {
      const pointsLen = seriesCache.pm[marketId] ? seriesCache.pm[marketId].length : 0;
      entry.series.applyOptions({
        visible: pmChecked && pointsLen > 0,
      });
    });
    if (priceChart) {
      priceChart.priceScale("pm").applyOptions({
        visible: pmChecked && pmSeriesMap.size > 0,
      });
    }
    const strikeLabels = document.getElementById("pm-strike-labels");
    if (strikeLabels) {
      strikeLabels.style.display = pmChecked ? "" : "none";
    }
    renderPmStrikeLabels();
  }

  function setupOptionsDropdown() {
    const btn = document.getElementById("options-menu-btn");
    const panel = document.getElementById("options-panel");
    const dropdown = document.getElementById("options-dropdown");
    if (!btn || !panel) return;

    btn.addEventListener("click", function (event) {
      event.stopPropagation();
      const isOpen = !panel.classList.contains("hidden");
      panel.classList.toggle("hidden", isOpen);
      btn.classList.toggle("open", !isOpen);
    });

    document.addEventListener("click", function (event) {
      if (!dropdown || dropdown.contains(event.target)) return;
      panel.classList.add("hidden");
      btn.classList.remove("open");
    });

    function onOptionsCheckboxChange(event) {
      const input = event.target;
      if (!input || input.type !== "checkbox") return;
      const symbol = input.value;
      const selected = new Set(chartStore.selectedOptionSymbols);
      if (input.checked) {
        selected.add(symbol);
      } else {
        selected.delete(symbol);
      }
      saveSelectedSymbols(chartStore.base, Array.from(selected));
      flushSaveLayout();
      loadChart(true);
    }

    const callsEl = document.getElementById("options-calls-list");
    const putsEl = document.getElementById("options-puts-list");
    if (callsEl) callsEl.addEventListener("change", onOptionsCheckboxChange);
    if (putsEl) putsEl.addEventListener("change", onOptionsCheckboxChange);
  }

  function syncTabActiveStates() {
    document.querySelectorAll("#asset-tabs button").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.base === chartStore.base);
    });
    document.querySelectorAll("#tf-tabs button").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.interval === chartStore.interval);
    });
  }

  function installToolbarClickRouting() {
    if (window.__voltaToolbarClickInstalled) {
      return;
    }
    window.__voltaToolbarClickInstalled = true;
    document.addEventListener(
      "click",
      function (event) {
        const ui = window.__voltaUi;
        if (!ui) {
          return;
        }
        const baseBtn = event.target.closest("#asset-tabs button[data-base]");
        if (baseBtn) {
          void ui.changeChartBase(baseBtn.getAttribute("data-base"));
          return;
        }
        const tfBtn = event.target.closest("#tf-tabs button[data-interval]");
        if (tfBtn) {
          ui.changeChartInterval(tfBtn.getAttribute("data-interval"));
        }
      },
      true
    );
  }

  function bindUi() {
    installToolbarClickRouting();
    syncTabActiveStates();

    ["toggle-futures", "toggle-options", "toggle-pm"].forEach(function (id) {
      const el = document.getElementById(id);
      if (el && !el.dataset.uiBound) {
        el.dataset.uiBound = "1";
        el.addEventListener("change", applyToggles);
      }
    });

    setupOptionsDropdown();
    setupPmDropdown();
  }

  function setupPmDropdown() {
    const btn = document.getElementById("pm-menu-btn");
    const panel = document.getElementById("pm-panel");
    const dropdown = document.getElementById("pm-dropdown");
    const importBtn = document.getElementById("pm-import-btn");
    const textarea = document.getElementById("pm-urls-import");
    const listEl = document.getElementById("pm-events-list");
    if (!btn || !panel) return;

    btn.addEventListener("click", function (event) {
      event.stopPropagation();
      const isOpen = !panel.classList.contains("hidden");
      panel.classList.toggle("hidden", isOpen);
      btn.classList.toggle("open", !isOpen);
    });

    document.addEventListener("click", function (event) {
      if (!dropdown || dropdown.contains(event.target)) return;
      panel.classList.add("hidden");
      btn.classList.remove("open");
    });

    if (listEl) {
      listEl.addEventListener("change", function (event) {
        const input = event.target;
        if (!input || input.type !== "radio") return;
        clearPmOverlay();
        saveSelectedPmEvent(chartStore.base, input.value);
        const selected = findPmEvent(chartStore.pmEvents, input.value);
        chartStore.pmEventUrl = selected ? selected.event_url : null;
        chartStore.pmEventEndDate = selected ? selected.event_end_date : null;
        startPmCountdown(chartStore.pmEventEndDate);
        flushSaveLayout();
        loadChart(true);
      });
    }

    if (importBtn && textarea) {
      importBtn.addEventListener("click", async function () {
        const text = textarea.value.trim();
        if (!text) return;
        importBtn.disabled = true;
        try {
          const result = await importPmEvents(chartStore.base, text);
          chartStore.pmEvents = result.events || [];
          applyPmSelectionFromEvents(chartStore.pmEvents, chartStore.base);
          renderPmEventsList(chartStore.base);
          textarea.value = "";
          clearPmOverlay();
          flushSaveLayout();
          await loadChart(true);
        } catch (err) {
          console.error(err);
          document.getElementById("legend").textContent = String(err.message || err);
        } finally {
          importBtn.disabled = false;
        }
      });
    }
  }

  function readPmUrlFromQuery() {
    const params = new URLSearchParams(window.location.search);
    return params.get("pm_url");
  }

  async function bootstrap() {
    bindUi();
    try {
      initCharts();
    } catch (err) {
      console.error("initCharts failed:", err);
      const legend = document.getElementById("legend");
      if (legend) {
        legend.textContent = "Chart init error: " + String(err.message || err);
      }
    }

    const pmUrlFromQuery = readPmUrlFromQuery();
    await loadPmEventsForBase(chartStore.base);

    if (pmUrlFromQuery) {
      try {
        const result = await importPmEvents(chartStore.base, pmUrlFromQuery);
        chartStore.pmEvents = result.events || [];
        applyPmSelectionFromEvents(chartStore.pmEvents, chartStore.base);
        renderPmEventsList(chartStore.base);
      } catch (err) {
        console.error(err);
        document.getElementById("legend").textContent = String(err.message || err);
      }
    }

    setupVisibilityListener();
    await loadChart(true);
  }

  function onBootstrapError(err) {
    console.error(err);
    const legend = document.getElementById("legend");
    if (legend) {
      legend.textContent = String(err.message || err);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bootstrap().catch(onBootstrapError);
    });
  } else {
    bootstrap().catch(onBootstrapError);
  }

  window.__voltaUi = {
    changeChartBase: changeChartBase,
    changeChartInterval: changeChartInterval,
    syncTabActiveStates: syncTabActiveStates,
  };
  window.chartStore = chartStore;
})();
