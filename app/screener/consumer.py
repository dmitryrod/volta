__all__ = ["Consumer"]

import asyncio
import functools
import json
import math
import time
from datetime import datetime, timezone
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

from unicex import (
    Exchange,
    KlineDict,
    LiquidationDict,
    MarketType,
    OpenInterestItem,
    TickerDailyItem,
    get_uni_client,
)
from unicex.extra import TimeoutTracker, normalize_ticker

from app.config import (
    build_signal_log_payload,
    get_logger,
    log_debug_event_async,
    log_signals_event_async,
)
from sqlalchemy import select

from app.database import Database, SignalORM
from app.models import SettingsDTO, SignalDTO, ScreeningResult
from app.test_signal_broadcast import broadcast_test_payload, test_stream_is_active
from app.utils import (
    SignalCounter,
    TelegramBot,
    format_filter_failure,
    generate_text,
)

from app.screener import scanner_runtime
from app.screener.test_mode_eval import (
    all_filters_ok,
    build_scanner_filter_max_list,
    evaluate_test_mode_snapshot,
    extract_peak_metric_for_scanner_row,
    no_enabled_filters_ok,
)

from .filters import (
    BlacklistFilter,
    DailyPriceFilter,
    DailyVolumeFilter,
    FundingRateFilter,
    LiquidationsSumFilter,
    OnlyUsdtPairsFilter,
    OpenInterestFilter,
    PumpDumpFilter,
    VolumeMultiplierFilter,
    WhitelistFilter,
)
from .parsers import ParsersDTO


def _symbol_check_pair(
    signal_counter: SignalCounter[str],
    test_enabled: bool,
    args: tuple[Any, ...],
) -> tuple[Any, dict[str, Any] | None, str]:
    """Запускает основную проверку фильтров и при необходимости снимок для режима «Тест».

    Returns:
        main: результат `_check_filters_for_symbol`.
        test_payload: снимок для SSE или None.
        symbol: тикерный символ (как в цикле Consumer).
    """
    symbol = args[0]
    main = Consumer._check_filters_for_symbol(*args)
    if not test_enabled:
        return main, None, symbol
    ticker = args[1]
    market_type = args[2]
    settings = args[3]
    ticker_daily = args[4]
    klines = args[5]
    oi = args[6]
    fr = args[7]
    liq = args[8]
    bl = args[9]
    wl = args[10]
    test_payload = evaluate_test_mode_snapshot(
        symbol,
        ticker,
        market_type,
        settings,
        ticker_daily,
        klines,
        oi,
        fr,
        liq,
        bl,
        wl,
        daily_signal_count=signal_counter.get(symbol),
    )
    return main, test_payload, symbol


def apply_scanner_filter_fire_edges(
    prev_ok_by_fid: dict[str, bool],
    fire_by_fid: dict[str, dict[str, Any]],
    test_filters: list[dict[str, Any]],
    start_ts: float,
    now_sec: float,
) -> None:
    """При переходе ok false→true фиксирует fire_at (UTC ISO) и fire_elapsed_ms от start_ts."""
    for row in test_filters:
        fid = str(row.get("id") or "")
        if not fid:
            continue
        curr = bool(row.get("ok"))
        prev = prev_ok_by_fid.get(fid, False)
        if prev is not True and curr:
            fire_by_fid[fid] = {
                "fire_at": datetime.now(timezone.utc).isoformat(),
                "fire_elapsed_ms": max(0, int((now_sec - start_ts) * 1000)),
            }
        prev_ok_by_fid[fid] = curr


def attach_fire_meta_to_test_filter_rows(
    test_filters: list[dict[str, Any]],
    fire_by_fid: dict[str, dict[str, Any]],
) -> None:
    """Добавляет в каждую строку test_filters поле fire_meta, если было срабатывание."""
    for row in test_filters:
        fid = str(row.get("id") or "")
        if fid and fid in fire_by_fid:
            row["fire_meta"] = dict(fire_by_fid[fid])


def _telegram_delivery_configured(settings: SettingsDTO) -> bool:
    """Пара токен + chat_id задана и годна для попытки отправки в Bot API."""
    token = (settings.bot_token or "").strip()
    return bool(token) and settings.chat_id is not None


class Consumer:
    """Прослушивает данные с парсеров и с определенной переодичностью
    проверяет данные на совпадение условий, чтобы отправить сигнал в телеграм."""

    _CHECK_INTERVAL_SEC: int = 1
    """Интервал проверки условий в секундах."""

    _FUNDING_RATE_CACHE_TTL_SEC: int = 55
    """TTL кэша фандинга по символу (сек). Снижает число запросов к API биржи."""

    def __init__(self, parsers: ParsersDTO, settings: SettingsDTO) -> None:
        """Инициализирует экземпляр класса.

        Params:
            parsers: ParsersDTO - Объект с работающими парсерами.
            settings: SettingsDTO - Объект с настройками скринера.
        """
        self._parsers = parsers
        self._settings = settings

        self._logger = get_logger("settings_" + str(settings.id))
        self._timeout_tracker = TimeoutTracker[str]()
        self._signal_counter = SignalCounter[str]()
        self._telegram_bot = TelegramBot() # must be called from async ctx
        self._is_running = True
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="filters")
        self._run_id = uuid4().hex
        self._cycle_id = 0
        self._last_signal_ts: float = 0.0
        # Эпоха (time.time) первого попадания символа в Scanner; сброс при выходе из режима.
        self._scanner_track_start: dict[str, float] = {}
        # symbol -> filter_id -> max наблюдаемого скаляра за сессию Scanner
        self._scanner_filter_peaks: dict[str, dict[str, float]] = {}
        # symbol -> filter_id -> последний известный ok (для фронта false→true)
        self._scanner_filter_prev_ok: dict[str, dict[str, bool]] = {}
        # symbol -> filter_id -> { fire_at, fire_elapsed_ms } последнего срабатывания
        self._scanner_filter_fire: dict[str, dict[str, dict[str, Any]]] = {}
        self._last_agg_empty_warn_ts: float = 0.0
        # Кэш фандинга: symbol -> (rate, expires_at)
        self._funding_rate_cache: dict[str, tuple[float, float]] = {}

    def update_settings(self, settings: SettingsDTO) -> None:
        """Обновляет настройки."""
        if settings.id != self._settings.id:
            raise ValueError("Settings ID mismatch")
        self._settings = settings

    @property
    def exchange(self) -> Exchange:
        """Возвращает биржу для поиска сигналов"""
        return self._settings.exchange

    @property
    def market_type(self) -> MarketType:
        """Возвращает тип рынка для поиска сигналов."""
        return self._settings.market_type
    
    @property
    def settings(self) -> SettingsDTO:
        """Возвращает настройки."""
        return self._settings
    
    @property
    def is_running(self) -> bool:
        """Возвращает статус запущенного процесса."""
        return self._is_running

    def _schedule_debug_log(self, **kwargs: Any) -> None:
        """Пишет debug.log в фоне: не блокирует цикл и отправку в Telegram при сбое json/очереди."""

        async def _runner() -> None:
            try:
                await log_debug_event_async(**kwargs)
            except Exception as exc:
                self._logger.warning(
                    "debug.json log failed ({}): {}",
                    type(exc).__name__,
                    exc,
                )

        asyncio.create_task(_runner())

    async def start(self) -> None:
        """Запускает процесс прослушивания данных и проверки условий."""
        while self._is_running:
            try:
                self._cycle_id += 1
                start_time = time.time()
                alert_tasks, cycle_meta = await self._check_filters()
                elapsed_time = time.time() - start_time
                self._logger.debug(f"Checked filters in {elapsed_time:.4f} seconds")
                if elapsed_time >= self._CHECK_INTERVAL_SEC:
                    self._logger.critical(
                        f"Consumer cycle exceeded tick interval: {elapsed_time:.4f}s "
                        f"(>={self._CHECK_INTERVAL_SEC}s)"
                    )

                if alert_tasks:
                    start_time = time.time()
                    results = await asyncio.gather(*alert_tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            self._logger.error(f"Error sending message: ({type(result)}) {result}")
                    elapsed_time = time.time() - start_time
                    self._logger.info(f"Sent {len(results)} messages in {elapsed_time:.4f} seconds")

                if self.settings.debug:
                    self._schedule_debug_log(
                        level="info",
                        screener_name=self.settings.name,
                        screener_id=self.settings.id,
                        exchange=str(self.settings.exchange.value),
                        market_type=str(self.settings.market_type.value),
                        event="cycle_end",
                        symbol=None,
                        payload={
                            **(cycle_meta or {}),
                            "elapsed_sec": round(elapsed_time, 6),
                            "has_alerts": bool(alert_tasks),
                        },
                        run_id=self._run_id,
                        cycle_id=self._cycle_id,
                    )
            except Exception as e:
                self._logger.exception(e)
                if self.settings.debug:
                    self._schedule_debug_log(
                        level="error",
                        screener_name=self.settings.name,
                        screener_id=self.settings.id,
                        exchange=str(self.settings.exchange.value),
                        market_type=str(self.settings.market_type.value),
                        event="error",
                        symbol=None,
                        payload={"location": "consumer.start"},
                        run_id=self._run_id,
                        cycle_id=self._cycle_id,
                        exc=e,
                    )
            await asyncio.sleep(self._CHECK_INTERVAL_SEC)

    async def stop(self) -> None:
        """Останавливает процесс прослушивания данных и проверки условий."""
        self._is_running = False
        await self._telegram_bot.close()

    async def _check_filters(self) -> tuple[list[asyncio.Task], dict]:
        """Проверяет данные по всем фильтрам и отправляет сигнал при успехе."""
        if not self.settings.any_filters_status:
            return [], {"reason": "no_filters_selected"}

        klines = await self._parsers.agg_trades.fetch_collected_data()
        ticker_daily = await self._parsers.ticker_daily.fetch_collected_data()
        now = time.time()
        if not klines and now - self._last_agg_empty_warn_ts >= 60.0:
            self._last_agg_empty_warn_ts = now
            self._logger.warning(
                "AggTrades: klines пуст по всем символам — фильтры (OI/Liquidations/pump/volume) "
                "не пройдут проверку «есть свеча», пока websocket aggTrades не начнёт отдавать сделки."
            )
        total_symbols = len(ticker_daily)
        blacklist = self.settings.parse_blacklist()
        whitelist = self.settings.parse_whitelist()
        if self.market_type == MarketType.FUTURES:
            open_interest = await self._parsers.open_interest.fetch_collected_data() # type: ignore
            funding_rate = await self._parsers.funding_rate.fetch_collected_data() # type: ignore
            liquidations = await self._parsers.liquidations.fetch_collected_data() # type: ignore
        else:
            open_interest = {}
            funding_rate = {}
            liquidations = {}

        tasks = []
        loop = asyncio.get_running_loop()
        await scanner_runtime.maybe_refresh_cache()
        test_enabled = scanner_runtime.should_compute_scanner_snapshot(
            test_stream_is_active()
        )
        blocked_timeout = 0
        blocked_day_limit = 0
        missing_klines = 0
        for symbol in ticker_daily:
            if self._timeout_tracker.is_blocked(symbol):
                self._logger.trace(f"[x] {symbol} is not valid. Reason: timeout")
                blocked_timeout += 1
                continue
            if self.settings.max_day_alerts and not self._signal_counter.is_within_limit(
                symbol, self.settings.max_day_alerts
            ):
                self._logger.trace(f"[x] {symbol} is not valid. Reason: max day alerts limit")
                blocked_day_limit += 1
                continue
            ticker = normalize_ticker(symbol)
            # Значение фандинга: сначала пытаемся по "сырому" symbol,
            # если нет — пробуем по нормализованному тикеру.
            symbol_funding_rate = funding_rate.get(symbol)
            if symbol_funding_rate is None:
                symbol_funding_rate = funding_rate.get(ticker, 0.0)
            tasks.append(
                loop.run_in_executor(
                    self._executor,
                    functools.partial(
                        _symbol_check_pair,
                        self._signal_counter,
                        test_enabled,
                        (
                            symbol,
                            ticker,
                            self.market_type,
                            self.settings,
                            ticker_daily[symbol],
                            klines.get(symbol, []),
                            open_interest.get(symbol, []),
                            symbol_funding_rate,
                            liquidations.get(ticker, []),
                            blacklist,
                            whitelist,
                        ),
                    ),
                )
            )

        if self.settings.debug:
            self._schedule_debug_log(
                level="info",
                screener_name=self.settings.name,
                screener_id=self.settings.id,
                exchange=str(self.settings.exchange.value),
                market_type=str(self.settings.market_type.value),
                event="cycle_start",
                symbol=None,
                payload={
                    "total_symbols": total_symbols,
                    "tasks_created": len(tasks),
                    "blocked_timeout": blocked_timeout,
                    "blocked_day_limit": blocked_day_limit,
                    "pipeline_blocker": "agg_trades_no_symbols"
                    if len(klines) == 0
                    else None,
                    "data_sizes": {
                        "klines_symbols": len(klines),
                        "ticker_daily_symbols": len(ticker_daily),
                        "open_interest_symbols": len(open_interest) if isinstance(open_interest, dict) else None,
                        "funding_rate_symbols": len(funding_rate) if isinstance(funding_rate, dict) else None,
                        "liquidations_symbols": len(liquidations) if isinstance(liquidations, dict) else None,
                    },
                    "parsers_age_sec": {
                        "agg_trades": round(
                            now
                            - (
                                self._parsers.agg_trades.last_update_ts
                                or self._parsers.agg_trades.started_ts
                            ),
                            3,
                        ),
                        "ticker_daily": round(
                            now
                            - (
                                self._parsers.ticker_daily.last_update_ts
                                or self._parsers.ticker_daily.started_ts
                            ),
                            3,
                        ),
                        "open_interest": (
                            None
                            if not self._parsers.open_interest
                            else round(
                                now
                                - (
                                    self._parsers.open_interest.last_update_ts
                                    or self._parsers.open_interest.started_ts
                                ),
                                3,
                            )
                        ),
                        "funding_rate": (
                            None
                            if not self._parsers.funding_rate
                            else round(
                                now
                                - (
                                    self._parsers.funding_rate.last_update_ts
                                    or self._parsers.funding_rate.started_ts
                                ),
                                3,
                            )
                        ),
                        "liquidations": (
                            None
                            if not self._parsers.liquidations
                            else round(
                                now
                                - (
                                    self._parsers.liquidations.last_update_ts
                                    or self._parsers.liquidations.started_ts
                                ),
                                3,
                            )
                        ),
                    },
                    "seconds_since_last_signal": None if not self._last_signal_ts else round(now - self._last_signal_ts, 3),
                },
                run_id=self._run_id,
                cycle_id=self._cycle_id,
            )

        alert_tasks = []
        total_signals = 0
        error_count = 0
        collect_fail_details = bool(getattr(self.settings, "debug", False))
        fail_reason_counts: dict[str, int] = {} if collect_fail_details else {}
        fail_samples: list[str] = [] if collect_fail_details else []
        liq_zero_window_failures = 0

        parsed: list[tuple[Any, dict[str, Any] | None, str]] = []
        if tasks:
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            raw_results = []

        for result in raw_results:
            if isinstance(result, Exception):
                self._logger.error(f"Error processing filters: ({type(result)}) {result}")
                error_count += 1
                if self.settings.debug:
                    self._schedule_debug_log(
                        level="error",
                        screener_name=self.settings.name,
                        screener_id=self.settings.id,
                        exchange=str(self.settings.exchange.value),
                        market_type=str(self.settings.market_type.value),
                        event="error",
                        symbol=None,
                        payload={"location": "consumer._check_filters.gather"},
                        run_id=self._run_id,
                        cycle_id=self._cycle_id,
                        exc=result,
                    )
                continue
            if isinstance(result, tuple) and len(result) == 3:
                main, test_payload, task_symbol = result
            elif isinstance(result, tuple) and len(result) == 2:
                main, test_payload = result
                task_symbol = ""
            else:
                main, test_payload = result, None
                task_symbol = ""
            parsed.append((main, test_payload, task_symbol))

        allowed: set[str] = set()
        scanner_eligible: set[str] = set()
        if test_enabled:
            scored: list[tuple[str, float]] = []
            for _main, test_payload, task_symbol in parsed:
                if test_payload is None or not task_symbol:
                    continue
                try:
                    sc = float(test_payload.get("score") or 0.0)
                except (TypeError, ValueError):
                    sc = 0.0
                if not math.isfinite(sc):
                    sc = 0.0
                scored.append((task_symbol, sc))
            scored.sort(key=lambda x: x[1], reverse=True)
            topn = scanner_runtime.max_cards()
            top_set = {s for s, _ in scored[:topn]}
            post_set = scanner_runtime.symbols_in_posttracking(self.settings.id)
            allowed = top_set | post_set
            # Символ с all_filters_ok может не попасть в top-N по score, но всё равно
            # даст продакшн-сигнал — сессию Scanner и pending-снимок нельзя резать в prune
            # и нельзя пропускать ветку обогащения (иначе card_snapshot_json в БД пустой).
            must_all_ok: set[str] = set()
            for _main, test_payload, task_symbol in parsed:
                if test_payload is None or not task_symbol:
                    continue
                if all_filters_ok(test_payload.get("test_filters") or []):
                    must_all_ok.add(task_symbol)
            scanner_eligible = allowed | must_all_ok
            scanner_runtime.prune_sessions_not_in_set(self.settings.id, scanner_eligible)

        pending_snap: dict[str, tuple[str | None, str | None]] = {}
        ex_s = str(self.settings.exchange.value)
        mt_s = str(self.settings.market_type.value)

        for main, test_payload, task_symbol in parsed:
            if test_enabled and task_symbol:
                if test_payload is not None and task_symbol in scanner_eligible:
                    start_ts = self._scanner_track_start.get(task_symbol)
                    if start_ts is None:
                        start_ts = time.time()
                        self._scanner_track_start[task_symbol] = start_ts
                    test_payload["scanner_tracked_since"] = datetime.fromtimestamp(
                        start_ts, tz=timezone.utc
                    ).isoformat()
                    peaks = self._scanner_filter_peaks.setdefault(task_symbol, {})
                    for row in test_payload.get("test_filters") or []:
                        fid, val = extract_peak_metric_for_scanner_row(row)
                        if val is None:
                            continue
                        old = peaks.get(fid)
                        if old is None or val > old:
                            peaks[fid] = val
                    test_payload["scanner_filter_max_list"] = build_scanner_filter_max_list(
                        test_payload.get("test_filters") or [],
                        peaks,
                    )
                    now_sec = time.time()
                    prev_ok_map = self._scanner_filter_prev_ok.setdefault(task_symbol, {})
                    fire_map = self._scanner_filter_fire.setdefault(task_symbol, {})
                    tf = test_payload.get("test_filters") or []
                    apply_scanner_filter_fire_edges(
                        prev_ok_map, fire_map, tf, start_ts, now_sec
                    )
                    attach_fire_meta_to_test_filter_rows(tf, fire_map)

                    removed_untriggered = False
                    if no_enabled_filters_ok(tf):
                        removed_untriggered = (
                            scanner_runtime.remove_untriggered_session_and_artifacts(
                                self.settings.id, task_symbol
                            )
                        )
                        if removed_untriggered:
                            self._scanner_track_start.pop(task_symbol, None)
                            self._scanner_filter_peaks.pop(task_symbol, None)
                            self._scanner_filter_prev_ok.pop(task_symbol, None)
                            self._scanner_filter_fire.pop(task_symbol, None)

                    skip_scanner_tail = removed_untriggered or (
                        no_enabled_filters_ok(tf)
                        and not scanner_runtime.session_is_triggered(
                            self.settings.id, task_symbol
                        )
                    )

                    if not skip_scanner_tail:
                        scanner_runtime.attach_tracking_meta(
                            test_payload,
                            screener_id=self.settings.id,
                            symbol=task_symbol,
                            screener_name=self.settings.name,
                            exchange=ex_s,
                            market_type=mt_s,
                        )
                        if all_filters_ok(tf):
                            trigger_wall = time.time()
                            elapsed_ms = int(max(0.0, (trigger_wall - start_ts) * 1000))
                            snap_copy = json.loads(json.dumps(test_payload, default=str))
                            snap_copy["scanner_duration_at_trigger_ms"] = elapsed_ms
                            snap_copy["scanner_snapshot_frozen"] = True
                            tid, snap = scanner_runtime.mark_triggered(
                                self.settings.id, task_symbol, snap_copy
                            )
                            if tid and snap:
                                pending_snap[task_symbol] = (tid, snap)
                        await scanner_runtime.maybe_persist_sample(
                            screener_id=self.settings.id,
                            symbol=task_symbol,
                            screener_name=self.settings.name,
                            exchange=ex_s,
                            market_type=mt_s,
                            enriched_payload=test_payload,
                            force=False,
                        )
                        test_payload["scanner_posttracking"] = (
                            scanner_runtime.is_posttracking(
                                self.settings.id, task_symbol
                            )
                        )
                        test_payload["scanner_show_close"] = test_payload[
                            "scanner_posttracking"
                        ]
                        if test_stream_is_active():
                            try:
                                await broadcast_test_payload(test_payload)
                            except Exception:
                                pass
                else:
                    self._scanner_track_start.pop(task_symbol, None)
                    self._scanner_filter_peaks.pop(task_symbol, None)
                    self._scanner_filter_prev_ok.pop(task_symbol, None)
                    self._scanner_filter_fire.pop(task_symbol, None)

            if isinstance(main, tuple) and isinstance(main[0], SignalDTO):
                signal, calc_debug = main
            else:
                signal, calc_debug = main, None

            if isinstance(signal, SignalDTO):
                try:
                    total_signals += 1
                    self._last_signal_ts = time.time()
                    self._timeout_tracker.block(signal.symbol, self.settings.timeout_sec)
                    daily_signal_count = self._signal_counter.add(signal.symbol)

                    await self._enrich_signal_with_funding_rate(signal)

                    self._logger.info(
                        "Signal created: symbol={}, funding_rate={}",
                        signal.symbol,
                        signal.funding_rate,
                    )

                    screening_result = ScreeningResult(
                        symbol=signal.symbol,
                        ticker=signal.ticker,
                        last_price=signal.last_price,
                        funding_rate=signal.funding_rate,
                        daily_volume=signal.daily_volume,
                        daily_price=signal.daily_price,
                        pd_start_price=signal.pd_start_price,
                        pd_final_price=signal.pd_final_price,
                        pd_price_change_pct=signal.pd_price_change_pct,
                        pd_price_change_usdt=signal.pd_price_change_usdt,
                        oi_start_value=signal.oi_start_value,
                        oi_final_value=signal.oi_final_value,
                        oi_change_pct=signal.oi_change_pct,
                        oi_change_coins=signal.oi_change_coins,
                        oi_change_usdt=signal.oi_change_usdt,
                        lq_amount_usdt=signal.lq_amount_usdt,
                        vl_multiplier=signal.vl_multiplier,
                    )

                    text = generate_text(
                        symbol=signal.symbol,
                        exchange=self.settings.exchange,
                        market_type=self.settings.market_type,
                        settings=self.settings,
                        result=screening_result,
                        daily_signal_count=daily_signal_count,
                    )

                    tr_id: str | None = None
                    card_json: str | None = None
                    if signal.symbol in pending_snap:
                        tr_id, card_json = pending_snap[signal.symbol]
                    if not card_json:
                        tid_fb, snap_fb = (
                            scanner_runtime.get_card_snapshot_for_signal_row(
                                self.settings.id, signal.symbol
                            )
                        )
                        if snap_fb:
                            tr_id = tr_id or tid_fb
                            card_json = snap_fb

                    alert_task = asyncio.create_task(
                        self._send_signal(
                            signal.symbol,
                            text,
                            signal=signal,
                            screening_result=screening_result,
                            calc_debug=calc_debug,
                            daily_signal_count=daily_signal_count,
                            tracking_id=tr_id,
                            card_snapshot_json=card_json,
                        )
                    )
                    alert_tasks.append(alert_task)

                    if self.settings.debug:
                        self._schedule_debug_log(
                            level="info",
                            screener_name=self.settings.name,
                            screener_id=self.settings.id,
                            exchange=str(self.settings.exchange.value),
                            market_type=str(self.settings.market_type.value),
                            event="signal",
                            symbol=signal.symbol,
                            payload={
                                "signal": signal.model_dump(),
                                "screening_result": asdict(screening_result),
                                "generate_text_input": {
                                    "symbol": signal.symbol,
                                    "exchange": str(self.settings.exchange.value),
                                    "market_type": str(self.settings.market_type.value),
                                    "text_template_type": str(self.settings.text_template_type.value),
                                    "daily_signal_count": daily_signal_count,
                                },
                                "message_text": text,
                                "calc": calc_debug,
                            },
                            run_id=self._run_id,
                            cycle_id=self._cycle_id,
                        )
                    self._logger.success(f"Processsed filters for {signal.symbol}")
                except Exception as e:
                    self._logger.error(f"Error sending filters: ({type(e)}) {e}")
                    error_count += 1
                    if self.settings.debug:
                        self._schedule_debug_log(
                            level="error",
                            screener_name=self.settings.name,
                            screener_id=self.settings.id,
                            exchange=str(self.settings.exchange.value),
                            market_type=str(self.settings.market_type.value),
                            event="error",
                            symbol=getattr(signal, "symbol", None),
                            payload={"location": "consumer._check_filters.signal_handling"},
                            run_id=self._run_id,
                            cycle_id=self._cycle_id,
                            exc=e,
                        )
            else:
                s = str(signal)
                if "no klines data" in s:
                    missing_klines += 1

                if collect_fail_details:
                    reason = "unknown"
                    try:
                        marker = "Reason:"
                        if marker in s:
                            reason = s.split(marker, 1)[1].strip()
                    except Exception:
                        reason = "unknown"

                    reason_key = reason
                    if len(reason_key) > 180:
                        reason_key = reason_key[:180] + "…"

                    fail_reason_counts[reason_key] = fail_reason_counts.get(
                        reason_key, 0
                    ) + 1
                    if len(fail_samples) < 5:
                        fail_samples.append(s[:220])

                    _lq_zero = (
                        "liquidations sum filter" in s
                        and (
                            "'amount_usdt': 0.0" in s
                            or '"amount_usdt": 0.0' in s
                        )
                    )
                    if _lq_zero:
                        liq_zero_window_failures += 1
                    if "whitelisted" not in s and "not USDT pair" not in s:
                        self._logger.debug(s)

        meta = {
            "total_symbols": total_symbols,
            "tasks_created": len(tasks),
            "signals": total_signals,
            "errors": error_count,
            "blocked_timeout": blocked_timeout,
            "blocked_day_limit": blocked_day_limit,
            "missing_klines": missing_klines,
            "lq_zero_window_failures": liq_zero_window_failures,
            "fail_reasons_top": dict(
                sorted(fail_reason_counts.items(), key=lambda kv: kv[1], reverse=True)[
                    :10
                ]
            )
            if collect_fail_details
            else {},
            "fail_samples": fail_samples if collect_fail_details else [],
        }
        return alert_tasks, meta

    @staticmethod
    def _telegram_response_for_signals_log(resp: dict | None) -> dict:
        if not isinstance(resp, dict):
            return {}
        result = resp.get("result")
        out: dict = {
            "ok": resp.get("ok"),
            "description": resp.get("description"),
        }
        if isinstance(result, dict):
            out["message_id"] = result.get("message_id")
            out["date"] = result.get("date")
            ch = result.get("chat")
            if isinstance(ch, dict):
                out["chat_id"] = ch.get("id")
            tx = result.get("text")
            if tx is not None:
                out["text_echo"] = tx
        return out

    async def _save_signal_to_db(
        self,
        *,
        symbol: str,
        telegram_text: str,
        telegram_ok: bool,
        error: str | None,
        tracking_id: str | None = None,
        card_snapshot_json: str | None = None,
    ) -> None:
        """Сохраняет запись о сигнале в таблицу signals. Не бросает исключений наружу.

        При непустом ``tracking_id`` вторая и последующие вставки с тем же id
        пропускаются (одна строка на сессию Scanner posttrigger / posttracking).
        """
        try:
            async with Database.session_context() as db:
                if tracking_id:
                    existing_id = await db.session.scalar(
                        select(SignalORM.id)
                        .where(SignalORM.tracking_id == tracking_id)
                        .limit(1)
                    )
                    if existing_id is not None:
                        self._logger.trace(
                            "skip duplicate signals row tracking_id={} symbol={}",
                            tracking_id,
                            symbol,
                        )
                        return
                record = SignalORM(
                    screener_name=self.settings.name,
                    screener_id=self.settings.id,
                    exchange=str(self.settings.exchange.value),
                    market_type=str(self.settings.market_type.value),
                    symbol=symbol,
                    telegram_text=telegram_text,
                    telegram_ok=telegram_ok,
                    error=error,
                    tracking_id=tracking_id,
                    card_snapshot_json=card_snapshot_json,
                )
                db.session.add(record)
                await db.commit()
        except Exception as exc:
            self._logger.warning("_save_signal_to_db failed: {}", exc)

    async def _send_signal(
        self,
        symbol: str,
        text: str,
        *,
        signal: SignalDTO,
        screening_result: ScreeningResult,
        calc_debug: dict | None,
        daily_signal_count: int,
        tracking_id: str | None = None,
        card_snapshot_json: str | None = None,
    ) -> dict:
        """Отправляет сообщение, пишет signals_log и debug-лог по результату."""
        payload_base = build_signal_log_payload(
            screener_name=self.settings.name,
            screener_id=self.settings.id,
            exchange=str(self.settings.exchange.value),
            market_type=str(self.settings.market_type.value),
            symbol=symbol,
            telegram_text=text,
            signal=signal.model_dump(),
            screening_result=asdict(screening_result),
            calc_debug=calc_debug,
            daily_signal_count=daily_signal_count,
            run_id=self._run_id,
            cycle_id=self._cycle_id,
            telegram_ok=False,
            telegram={},
            error=None,
        )
        if card_snapshot_json:
            try:
                snap = json.loads(card_snapshot_json)
                if isinstance(snap, dict) and snap:
                    payload_base["card_snapshot"] = snap
            except (json.JSONDecodeError, TypeError):
                pass
        if tracking_id:
            payload_base["tracking_id"] = tracking_id

        if not _telegram_delivery_configured(self.settings):
            self._logger.trace(
                "telegram skipped (not configured) screener_id={} symbol={}",
                self.settings.id,
                symbol,
            )
            payload_base["telegram_ok"] = False
            payload_base["error"] = None
            await log_signals_event_async(payload_base)
            await self._save_signal_to_db(
                symbol=symbol,
                telegram_text=text,
                telegram_ok=False,
                error=None,
                tracking_id=tracking_id,
                card_snapshot_json=card_snapshot_json,
            )
            if self.settings.debug:
                self._schedule_debug_log(
                    level="info",
                    screener_name=self.settings.name,
                    screener_id=self.settings.id,
                    exchange=str(self.settings.exchange.value),
                    market_type=str(self.settings.market_type.value),
                    event="telegram_skipped",
                    symbol=symbol,
                    payload={"reason": "not_configured"},
                    run_id=self._run_id,
                    cycle_id=self._cycle_id,
                )
            return {}

        try:
            chat_id = self.settings.chat_id
            token = (self.settings.bot_token or "").strip()
            assert chat_id is not None and token
            resp = await self._telegram_bot.send_message(
                bot_token=token,
                chat_id=chat_id,
                text=text,
            )
            payload_base["telegram_ok"] = True
            payload_base["telegram"] = self._telegram_response_for_signals_log(resp)
            await log_signals_event_async(payload_base)
            await self._save_signal_to_db(
                symbol=symbol,
                telegram_text=text,
                telegram_ok=True,
                error=None,
                tracking_id=tracking_id,
                card_snapshot_json=card_snapshot_json,
            )
            if self.settings.debug:
                result = resp.get("result") if isinstance(resp, dict) else None
                safe_telegram = {
                    "ok": resp.get("ok") if isinstance(resp, dict) else None,
                    "description": resp.get("description") if isinstance(resp, dict) else None,
                }
                if isinstance(result, dict):
                    safe_telegram["message_id"] = result.get("message_id")
                    safe_telegram["date"] = result.get("date")
                self._schedule_debug_log(
                    level="info",
                    screener_name=self.settings.name,
                    screener_id=self.settings.id,
                    exchange=str(self.settings.exchange.value),
                    market_type=str(self.settings.market_type.value),
                    event="telegram_sent",
                    symbol=symbol,
                    payload={
                        "ok": True,
                        "message_len": len(text or ""),
                        "telegram": safe_telegram,
                    },
                    run_id=self._run_id,
                    cycle_id=self._cycle_id,
                )
            return resp
        except Exception as e:
            payload_base["telegram_ok"] = False
            payload_base["error"] = str(e)
            self._logger.warning(
                "telegram send failed screener_id={} symbol={}: {}",
                self.settings.id,
                symbol,
                e,
            )
            await log_signals_event_async(payload_base)
            await self._save_signal_to_db(
                symbol=symbol,
                telegram_text=text,
                telegram_ok=False,
                error=str(e),
                tracking_id=tracking_id,
                card_snapshot_json=card_snapshot_json,
            )
            if self.settings.debug:
                self._schedule_debug_log(
                    level="error",
                    screener_name=self.settings.name,
                    screener_id=self.settings.id,
                    exchange=str(self.settings.exchange.value),
                    market_type=str(self.settings.market_type.value),
                    event="telegram_error",
                    symbol=symbol,
                    payload={
                        "ok": False,
                        "message_len": len(text or ""),
                    },
                    run_id=self._run_id,
                    cycle_id=self._cycle_id,
                    exc=e,
                )
            return {}

    async def _enrich_signal_with_funding_rate(self, signal: SignalDTO) -> None:
        """Добирает актуальный фандинг по символу, если парсер не заполнил его.

        Использует TTL-кэш, чтобы не дергать API биржи при повторных сигналах по тому же тикеру.
        """
        if self.market_type != MarketType.FUTURES:
            return
        if signal.funding_rate not in (0.0, 0):
            return

        now = time.time()
        cached = self._funding_rate_cache.get(signal.symbol)
        if cached is not None and cached[1] > now:
            signal.funding_rate = cached[0]
            return

        try:
            client_factory = get_uni_client(self.exchange)
            client = await client_factory.create()
            async with client:
                value = await client.funding_rate(signal.symbol)  # type: ignore[arg-type]
            rate = float(value)
            signal.funding_rate = rate
            self._funding_rate_cache[signal.symbol] = (
                rate,
                now + self._FUNDING_RATE_CACHE_TTL_SEC,
            )
            self._logger.info(
                "Enriched funding rate for symbol {}: {}",
                signal.symbol,
                signal.funding_rate,
            )
        except Exception as e:
            self._logger.error(
                "Error fetching funding rate on-demand for {}: ({}) {}",
                signal.symbol,
                type(e),
                e,
            )

    @staticmethod
    def _check_filters_for_symbol(
        symbol: str,
        ticker: str,
        market_type: MarketType,
        settings: SettingsDTO,
        ticker_daily: TickerDailyItem,
        klines: list[KlineDict],
        open_interest: list[OpenInterestItem],
        funding_rate: float,
        liquidations: list[LiquidationDict],
        blacklist: set[str],
        whitelist: set[str],
    ) -> str | tuple[SignalDTO, dict]:
        """Проверяет фильтры для конкретного тикера."""
        only_usdt_pair_result = OnlyUsdtPairsFilter.process(symbol)
        if not only_usdt_pair_result.ok:
            return f"[x] {symbol}. Reason: not USDT pair. Details: {only_usdt_pair_result}"

        # Если по тикеру ещё нет ни одной свечи, пропускаем его, чтобы не падать на индексах.
        if not klines:
            return f"[x] {symbol}. Reason: no klines data"

        blacklist_result = BlacklistFilter.process(ticker, blacklist)
        if not blacklist_result.ok:
            return f"[x] {symbol}. Reason: blacklisted. Details: {blacklist_result}"

        whitelist_result = WhitelistFilter.process(ticker, whitelist)
        if not whitelist_result.ok:
            return f"[x] {symbol}. Reason: not whitelisted. Details: {whitelist_result}"
        
        if settings.dv_status:
            daily_volume_result = DailyVolumeFilter.process(
                ticker_daily=ticker_daily,
                dv_min_usd=settings.dv_min_usd,
                dv_max_usd=settings.dv_max_usd,
            )
            if not daily_volume_result.ok:
                return f"[x] {symbol}. Reason: daily volume filter. Details: {daily_volume_result}"

        if settings.dp_status:
            daily_price_result = DailyPriceFilter.process(
                ticker_daily=ticker_daily,
                dp_min_pct=settings.dp_min_pct,
                dp_max_pct=settings.dp_max_pct,
            )
            if not daily_price_result.ok:
                return f"[x] {symbol}. Reason: daily price filter. Details: {daily_price_result}"

        if settings.pd_status:
            pump_dump_result = PumpDumpFilter.process(
                klines = klines,
                pd_interval_sec = settings.pd_interval_sec,
                pd_min_change_pct = settings.pd_min_change_pct,
            )
            if not pump_dump_result.ok:
                return f"[x] {symbol}. Reason: daily pump dump filter. Details: {pump_dump_result}"
        else:
            pump_dump_result = None
        
        if settings.vl_status:
            volume_multiplier_result = VolumeMultiplierFilter.process(
                klines=klines,
                ticker_daily=ticker_daily,
                vl_interval_sec=settings.vl_interval_sec, # type: ignore
                vl_min_multiplier=settings.vl_min_multiplier, # type: ignore
            )
            if not volume_multiplier_result.ok:
                return f"[x] {symbol}. Reason: volume multiplier filter. Details: {volume_multiplier_result}"
        else:
            volume_multiplier_result = None

        last_price = klines[-1]["c"]

        if market_type == MarketType.FUTURES:
            if settings.oi_status:
                open_interest_result = OpenInterestFilter.process(
                    open_interest=open_interest,
                    oi_interval_sec=settings.oi_interval_sec,
                    oi_min_change_pct=settings.oi_min_change_pct,
                    oi_min_change_usd=settings.oi_min_change_usd,
                    last_price=last_price,
                )
                if not open_interest_result.ok:
                    return f"[x] {symbol}. Reason: open interest filter. Details: {open_interest_result}"
            else:
                open_interest_result = None

            if settings.fr_status:
                funding_rate_result = FundingRateFilter.process(
                    funding_rate=funding_rate,
                    fr_min_value_pct=settings.fr_min_value_pct,
                    fr_max_value_pct=settings.fr_max_value_pct,
                )
                if not funding_rate_result.ok:
                    return (
                        f"[x] {symbol}. Reason: funding rate filter. Details: {funding_rate_result}"
                    )
            else: 
                funding_rate_result = None

            if settings.lq_status:
                liquidations_result = LiquidationsSumFilter.process(
                    liquidations=liquidations,
                    lq_interval_sec=settings.lq_interval_sec,
                    lq_min_amount_usd=settings.lq_min_amount_usd,
                    lq_min_amount_pct=settings.lq_min_amount_pct,
                    daily_volume_usd=ticker_daily["q"],
                )
                if not liquidations_result.ok:
                    return f"[x] {symbol}. Reason: liquidations sum filter. Details: {liquidations_result}"
            else:
                liquidations_result = None
        else:
            open_interest_result = None
            funding_rate_result = None
            liquidations_result = None
        
        signal = SignalDTO(
            timestamp=int(time.time()),
            datetime=time.ctime(),
            symbol=symbol,
            ticker=ticker,
            last_price=last_price,
            funding_rate=funding_rate,
            daily_volume=ticker_daily["q"],
            daily_price=ticker_daily["p"],
            pd_start_price=pump_dump_result.start_price if pump_dump_result else None,
            pd_final_price=pump_dump_result.final_price if pump_dump_result else None,
            pd_price_change_pct=pump_dump_result.price_change_pct if pump_dump_result else None,
            pd_price_change_usdt=pump_dump_result.price_change_usdt  if pump_dump_result else None,
            oi_start_value=open_interest_result.start_value if open_interest_result else None,
            oi_final_value=open_interest_result.final_value if open_interest_result else None,
            oi_change_pct=open_interest_result.change_pct if open_interest_result else None,
            oi_change_coins=open_interest_result.change_coins if open_interest_result else None,
            oi_change_usdt=open_interest_result.change_usdt if open_interest_result else None,
            lq_amount_usdt=liquidations_result.amount_usdt if liquidations_result else None,
            vl_multiplier=volume_multiplier_result.multiplier if volume_multiplier_result else None,
        )

        calc_debug = {
            "inputs": {
                "ticker_daily": dict(ticker_daily),
                "last_price": last_price,
                "funding_rate_in": funding_rate,
                "klines_len": len(klines),
                "open_interest_len": len(open_interest) if open_interest is not None else 0,
                "liquidations_len": len(liquidations) if liquidations is not None else 0,
            },
            "settings": {
                "pd_status": settings.pd_status,
                "pd_interval_sec": settings.pd_interval_sec,
                "pd_min_change_pct": settings.pd_min_change_pct,
                "oi_status": settings.oi_status,
                "oi_interval_sec": settings.oi_interval_sec,
                "oi_min_change_pct": settings.oi_min_change_pct,
                "oi_min_change_usd": settings.oi_min_change_usd,
                "fr_status": settings.fr_status,
                "fr_min_value_pct": settings.fr_min_value_pct,
                "fr_max_value_pct": settings.fr_max_value_pct,
                "vl_status": settings.vl_status,
                "vl_interval_sec": settings.vl_interval_sec,
                "vl_min_multiplier": settings.vl_min_multiplier,
                "lq_status": settings.lq_status,
                "lq_interval_sec": settings.lq_interval_sec,
                "lq_min_amount_usd": settings.lq_min_amount_usd,
                "lq_min_amount_pct": settings.lq_min_amount_pct,
                "dv_status": settings.dv_status,
                "dv_min_usd": settings.dv_min_usd,
                "dv_max_usd": settings.dv_max_usd,
                "dp_status": settings.dp_status,
                "dp_min_pct": settings.dp_min_pct,
                "dp_max_pct": settings.dp_max_pct,
                "timeout_sec": settings.timeout_sec,
                "max_day_alerts": settings.max_day_alerts,
                "text_template_type": str(settings.text_template_type.value),
            },
            "filters": {
                "pump_dump": None if pump_dump_result is None else {
                    "start_price": pump_dump_result.start_price,
                    "final_price": pump_dump_result.final_price,
                    "price_change_pct": pump_dump_result.price_change_pct,
                    "price_change_usdt": pump_dump_result.price_change_usdt,
                },
                "volume_multiplier": None if volume_multiplier_result is None else {
                    "multiplier": volume_multiplier_result.multiplier,
                },
                "open_interest": None if open_interest_result is None else {
                    "start_value": open_interest_result.start_value,
                    "final_value": open_interest_result.final_value,
                    "change_pct": open_interest_result.change_pct,
                    "change_coins": open_interest_result.change_coins,
                    "change_usdt": open_interest_result.change_usdt,
                },
                "funding_rate": None if funding_rate_result is None else {
                    "funding_rate": funding_rate,
                },
                "liquidations": None if liquidations_result is None else {
                    "amount_usdt": liquidations_result.amount_usdt,
                },
            },
        }

        return signal, calc_debug