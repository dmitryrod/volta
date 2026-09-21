__all__ = ["Operator"]

import asyncio
from collections.abc import Awaitable, Callable
import os
import random
import time
from uuid import uuid4

from unicex import Exchange, MarketType

from app.config import get_logger, log_debug_event, log_signals_event
from app.database import Database
from app.schemas import SettingsDTO
from app.utils.connectivity import is_transient_network_error, wait_for_internet

from .consumer import Consumer
from .parsers import (
    AggTradesParser,
    FundingRateParser,
    LiquidationsParser,
    OpenInterestParser,
    ParsersDTO,
    TickerDailyParser,
)


class Operator:
    """Управляет созданием и запуском парсеров и консьюмеров."""

    _UPDATE_INTERVAL_SEC: int = 3
    """Интервал обновления настроек в секундах."""

    _STALE_THRESHOLD_SEC: int = 60
    """Порог устаревания данных парсеров (сек)."""

    _STALE_LOG_THROTTLE_SEC: int = 60
    """Как часто можно писать stale_data для одного скринера (сек)."""

    _WS_STALE_RESTART_SEC: int = 90
    """Возраст данных (сек), после которого watchdog перезапускает websocket-парсер."""

    _WS_RESTART_COOLDOWN_BASE_SEC: float = 30.0
    """Минимальный интервал между принудительными рестартами одной пары (сек)."""

    _WS_RESTART_COOLDOWN_MAX_SEC: float = 300.0
    """Потолок backoff между рестартами (сек)."""

    _WS_RESTART_JITTER_SEC: float = 8.0
    """Случайная добавка к cooldown, чтобы не синхронно рестартовать всё."""

    _WS_PERIODIC_RECYCLE_DEFAULT_SEC: int = 14400
    """Если WS_PERIODIC_RECYCLE_SEC не задана или пуста — плановый recycle agg/liq (4 ч)."""

    def __init__(self) -> None:
        """Инициализирует оператора."""
        self._logger = get_logger("operator")
        self._is_running = False
        self._run_id = uuid4().hex
        self._monitor_cycle_id = 0
        self._last_stale_log_ts: dict[tuple[int, Exchange, MarketType], float] = {}
        self._last_task_done_log_ts: dict[tuple[int, Exchange, MarketType], float] = {}
        self._task_exception_logged: set[int] = set()

        self._ws_next_restart_ok: dict[tuple[Exchange, MarketType], float] = {}
        self._ws_restart_backoff_sec: dict[tuple[Exchange, MarketType], float] = {}

        self._parsers: dict[tuple[Exchange, MarketType], ParsersDTO] = {}
        """Настроенные для каждой пары биржа+рынок парсеры."""

        self._parser_tasks: dict[tuple[Exchange, MarketType], dict[str, asyncio.Task]] = {}
        """Запущенные задачи парсеров для каждой пары биржа+рынок."""

        self._consumers: dict[tuple[int, Exchange, MarketType], Consumer] = {}
        """Активные консьюмеры по ключу (settings.id, exchange, market_type)."""

        self._consumer_tasks: dict[tuple[int, Exchange, MarketType], asyncio.Task] = {}
        """Задачи для фонового запуска консьюмеров."""

        recycle_raw = os.getenv("WS_PERIODIC_RECYCLE_SEC")
        if recycle_raw is None or not str(recycle_raw).strip():
            self._ws_periodic_recycle_sec = self._WS_PERIODIC_RECYCLE_DEFAULT_SEC
        else:
            try:
                self._ws_periodic_recycle_sec = max(
                    0, int(str(recycle_raw).strip().split()[0])
                )
            except (ValueError, IndexError):
                self._logger.warning(
                    "WS_PERIODIC_RECYCLE_SEC invalid ({!r}); using default {}s",
                    recycle_raw,
                    self._WS_PERIODIC_RECYCLE_DEFAULT_SEC,
                )
                self._ws_periodic_recycle_sec = self._WS_PERIODIC_RECYCLE_DEFAULT_SEC
        self._last_ws_periodic_recycle_ts: dict[tuple[Exchange, MarketType], float] = {}

    async def start(self) -> None:
        """Запускает цикл обновления настроек и управление процессами."""
        if self._is_running:
            raise RuntimeError("Operator is already running")

        self._is_running = True
        self._logger.info("Operator started")
        log_signals_event(
            {
                "kind": "lifecycle",
                "action": "operator_started",
                "run_id": self._run_id,
            }
        )
        if self._ws_periodic_recycle_sec > 0:
            self._logger.info(
                "WebSocket periodic recycle: every {}s (WS_PERIODIC_RECYCLE_SEC; default {} if unset)",
                self._ws_periodic_recycle_sec,
                self._WS_PERIODIC_RECYCLE_DEFAULT_SEC,
            )
        else:
            self._logger.info(
                "WebSocket periodic recycle: off (WS_PERIODIC_RECYCLE_SEC=0)"
            )

        while self._is_running:
            self._monitor_cycle_id += 1
            try:
                settings_list = await self._fetch_settings()
            except Exception as exc:
                self._logger.exception(f"Error fetching settings: {exc}")
                if is_transient_network_error(exc):
                    await wait_for_internet(logger=self._logger, log_name="database")
                await asyncio.sleep(self._UPDATE_INTERVAL_SEC)
                continue

            try:
                await self._update_parsers(settings_list)
            except Exception as exc:
                self._logger.exception(f"Error updating parsers: {exc}")
                if is_transient_network_error(exc):
                    await wait_for_internet(logger=self._logger, log_name="update_parsers")

            # Автовосстановление parser-task: если websocket/loop умер,
            # поднимаем задачу заново без перезапуска всего процесса.
            try:
                self._restart_dead_parser_tasks()
            except Exception as exc:
                self._logger.exception(f"Error restarting dead parser tasks: {exc}")

            try:
                await self._maybe_restart_stale_websocket_parsers(settings_list)
            except Exception as exc:
                self._logger.exception(f"Error in websocket stale watchdog: {exc}")
                if is_transient_network_error(exc):
                    await wait_for_internet(logger=self._logger, log_name="websocket_watchdog")

            try:
                await self._maybe_periodic_recycle_websocket_parsers(settings_list)
            except Exception as exc:
                self._logger.exception(f"Error in websocket periodic recycle: {exc}")

            try:
                await self._update_consumers(settings_list)
            except Exception as exc:
                self._logger.exception(f"Error updating consumers: {exc}")
                if is_transient_network_error(exc):
                    await wait_for_internet(logger=self._logger, log_name="update_consumers")

            # Мониторинг зависаний/устаревших данных — после обновления состава процессов
            try:
                self._monitor_health(settings_list)
            except Exception as exc:
                self._logger.exception(f"Error monitoring health: {exc}")

            await asyncio.sleep(self._UPDATE_INTERVAL_SEC)

    def _task_state(self, task: asyncio.Task | None) -> dict:
        if task is None:
            return {"present": False}
        state = {
            "present": True,
            "done": task.done(),
            "cancelled": task.cancelled(),
            "name": getattr(task, "get_name", lambda: None)(),
        }
        if task.done() and not task.cancelled():
            try:
                exc = task.exception()
                state["exception"] = None if exc is None else {"type": type(exc).__name__, "message": str(exc)}
            except Exception as e:  # pragma: no cover
                state["exception"] = {"type": type(e).__name__, "message": str(e)}
        return state

    def _websocket_state(self, parsers: ParsersDTO) -> dict:
        # best-effort: внутренние поля, без падений
        out: dict = {}
        try:
            websockets = getattr(parsers.agg_trades, "_websockets", None)
            if websockets is not None:
                out["agg_trades"] = {
                    "total": len(websockets),
                    "running": sum(1 for ws in websockets if getattr(ws, "running", False)),
                }
        except Exception:
            pass
        try:
            lq = getattr(parsers, "liquidations", None)
            if lq is not None:
                websockets = getattr(lq, "_liquidation_websockets", None)
                if websockets is not None:
                    out["liquidations"] = {
                        "total": len(websockets),
                        "running": sum(1 for ws in websockets if getattr(ws, "running", False)),
                    }
        except Exception:
            pass
        return out

    def _parser_task_factories(self, parsers: ParsersDTO) -> dict[str, Callable[[], Awaitable[None]]]:
        factories: dict[str, Callable[[], Awaitable[None]]] = {
            "agg_trades": parsers.agg_trades.start,
            "ticker_daily": parsers.ticker_daily.start,
        }
        if parsers.funding_rate:
            factories["funding_rate"] = parsers.funding_rate.start
        if parsers.liquidations:
            factories["liquidations"] = parsers.liquidations.start
        if parsers.open_interest:
            factories["open_interest"] = parsers.open_interest.start
        return factories

    @staticmethod
    def _effective_parser_age(parser_obj, now: float) -> float:
        ts = getattr(parser_obj, "last_update_ts", 0.0) or getattr(
            parser_obj, "started_ts", 0.0
        )
        return round(now - float(ts or now), 3)

    async def _restart_websocket_parser_task(
        self,
        pair_key: tuple[Exchange, MarketType],
        name: str,
        *,
        restart_reason: str = "unspecified",
    ) -> None:
        parsers = self._parsers.get(pair_key)
        if not parsers:
            return
        if name == "agg_trades":
            parser = parsers.agg_trades
        elif name == "liquidations" and parsers.liquidations:
            parser = parsers.liquidations
        else:
            return

        task_map = self._parser_tasks.setdefault(pair_key, {})
        old_task = task_map.get(name)

        await parser.stop()
        if old_task is not None and not old_task.done():
            old_task.cancel()
            await asyncio.gather(old_task, return_exceptions=True)

        parser.mark_running()
        factories = self._parser_task_factories(parsers)
        start_fn = factories.get(name)
        if not start_fn:
            return
        task_map[name] = asyncio.create_task(
            start_fn(),
            name=f"parser:{name}:{pair_key[0].value}:{pair_key[1].value}",
        )
        self._logger.warning(
            "Watchdog: restarted websocket parser '{}' for {}:{}",
            name,
            pair_key[0].value,
            pair_key[1].value,
        )
        log_signals_event(
            {
                "kind": "lifecycle",
                "action": "parser_websocket_restarted",
                "parser": name,
                "exchange": str(pair_key[0].value),
                "market_type": str(pair_key[1].value),
                "restart_reason": restart_reason,
                "run_id": self._run_id,
            }
        )

    async def _maybe_periodic_recycle_websocket_parsers(
        self, settings_list: list[SettingsDTO]
    ) -> None:
        """Плановый перезапуск agg_trades (+ liquidations на фьючерсах), если recycle > 0 (см. WS_PERIODIC_RECYCLE_SEC)."""
        if self._ws_periodic_recycle_sec <= 0:
            return
        required_pairs = {(s.exchange, s.market_type) for s in settings_list}
        now = time.time()
        for pair_key in list(self._parsers.keys()):
            if pair_key not in required_pairs:
                continue
            exchange, market_type = pair_key
            parsers = self._parsers[pair_key]
            last = self._last_ws_periodic_recycle_ts.get(pair_key)
            if last is None:
                # Первая встреча пары: только ставим отсчёт, без рестарта (иначе recycle на старте при last=0).
                self._last_ws_periodic_recycle_ts[pair_key] = now
                continue
            if now - last < self._ws_periodic_recycle_sec:
                continue
            self._last_ws_periodic_recycle_ts[pair_key] = now
            self._logger.warning(
                "Periodic WS recycle (WS_PERIODIC_RECYCLE_SEC={}): restarting agg_trades{} for {}:{}",
                self._ws_periodic_recycle_sec,
                " + liquidations" if market_type == MarketType.FUTURES and parsers.liquidations else "",
                exchange.value,
                market_type.value,
            )
            await self._restart_websocket_parser_task(
                pair_key, "agg_trades", restart_reason="periodic_recycle"
            )
            if market_type == MarketType.FUTURES and parsers.liquidations:
                await self._restart_websocket_parser_task(
                    pair_key, "liquidations", restart_reason="periodic_recycle"
                )

    async def _maybe_restart_stale_websocket_parsers(
        self, settings_list: list[SettingsDTO]
    ) -> None:
        """Принудительно перезапускает agg_trades / liquidations при устаревании данных (не только task.done())."""
        required_pairs = {(s.exchange, s.market_type) for s in settings_list}
        now = time.time()
        half = self._WS_STALE_RESTART_SEC * 0.5

        for pair_key in list(self._parsers.keys()):
            if pair_key not in required_pairs:
                continue
            parsers = self._parsers[pair_key]
            _, market_type = pair_key

            age_agg = self._effective_parser_age(parsers.agg_trades, now)
            if market_type == MarketType.FUTURES and parsers.liquidations:
                age_lq = self._effective_parser_age(parsers.liquidations, now)
            else:
                age_lq = 0.0

            healthy = age_agg < half and (
                market_type != MarketType.FUTURES
                or not parsers.liquidations
                or age_lq < half
            )
            if healthy:
                self._ws_restart_backoff_sec[pair_key] = self._WS_RESTART_COOLDOWN_BASE_SEC
                continue

            stale_agg = age_agg >= self._WS_STALE_RESTART_SEC
            stale_lq = (
                market_type == MarketType.FUTURES
                and parsers.liquidations is not None
                and age_lq >= self._WS_STALE_RESTART_SEC
            )
            if not stale_agg and not stale_lq:
                continue

            if now < self._ws_next_restart_ok.get(pair_key, 0.0):
                continue

            backoff = self._ws_restart_backoff_sec.get(
                pair_key, self._WS_RESTART_COOLDOWN_BASE_SEC
            )
            jitter = random.uniform(0.0, self._WS_RESTART_JITTER_SEC)
            self._ws_next_restart_ok[pair_key] = now + backoff + jitter
            self._ws_restart_backoff_sec[pair_key] = min(
                max(backoff * 2.0, self._WS_RESTART_COOLDOWN_BASE_SEC),
                self._WS_RESTART_COOLDOWN_MAX_SEC,
            )

            self._logger.warning(
                "Watchdog: stale websocket data (agg_age={}s lq_age={}s) — restarting parsers for {}:{}",
                age_agg,
                age_lq if parsers.liquidations else None,
                pair_key[0].value,
                pair_key[1].value,
            )

            if stale_agg:
                await self._restart_websocket_parser_task(
                    pair_key, "agg_trades", restart_reason="stale_data_watchdog"
                )
            if stale_lq:
                await self._restart_websocket_parser_task(
                    pair_key, "liquidations", restart_reason="stale_data_watchdog"
                )

    def _restart_dead_parser_tasks(self) -> None:
        for pair_key, parsers in list(self._parsers.items()):
            task_map = self._parser_tasks.setdefault(pair_key, {})
            for task_name, start_fn in self._parser_task_factories(parsers).items():
                task = task_map.get(task_name)
                if task is not None and not task.done():
                    continue

                if task is not None and task.cancelled():
                    continue

                new_task = asyncio.create_task(
                    start_fn(),
                    name=f"parser:{task_name}:{pair_key[0].value}:{pair_key[1].value}",
                )
                task_map[task_name] = new_task
                self._logger.warning(
                    "Restarted dead parser-task {} for {}:{}",
                    task_name,
                    pair_key[0].value,
                    pair_key[1].value,
                )
                log_signals_event(
                    {
                        "kind": "lifecycle",
                        "action": "parser_task_recovered",
                        "parser": task_name,
                        "exchange": str(pair_key[0].value),
                        "market_type": str(pair_key[1].value),
                        "run_id": self._run_id,
                    }
                )

    def _monitor_health(self, settings_list: list[SettingsDTO]) -> None:
        now = time.time()
        settings_by_key: dict[tuple[int, Exchange, MarketType], SettingsDTO] = {
            (s.id, s.exchange, s.market_type): s for s in settings_list
        }

        # Сначала: ловим падения parser-task сразу (по паре биржа/рынок),
        # привязываем к любому debug-включенному скринеру этой пары.
        debug_settings_by_pair: dict[tuple[Exchange, MarketType], SettingsDTO] = {}
        for s in settings_list:
            if getattr(s, "debug", False):
                debug_settings_by_pair.setdefault((s.exchange, s.market_type), s)

        for pair_key, task_map in list(self._parser_tasks.items()):
            settings = debug_settings_by_pair.get(pair_key)
            if not settings:
                continue
            for t in list((task_map or {}).values()):
                if t is None:
                    continue
                tid = id(t)
                if tid in self._task_exception_logged:
                    continue
                if not t.done() or t.cancelled():
                    continue
                exc = None
                try:
                    exc = t.exception()
                except Exception as e:  # pragma: no cover
                    exc = e
                if exc is None:
                    continue
                self._task_exception_logged.add(tid)
                log_debug_event(
                    level="error",
                    screener_name=settings.name,
                    screener_id=settings.id,
                    exchange=str(settings.exchange.value),
                    market_type=str(settings.market_type.value),
                    event="task_exception",
                    symbol=None,
                    payload={
                        "kind": "parser_task",
                        "pair": {
                            "exchange": str(pair_key[0].value),
                            "market_type": str(pair_key[1].value),
                        },
                        "task": self._task_state(t),
                    },
                    run_id=self._run_id,
                    cycle_id=self._monitor_cycle_id,
                    exc=exc,
                )

        for key, consumer in list(self._consumers.items()):
            settings = settings_by_key.get(key)
            if not settings or not getattr(settings, "debug", False):
                continue

            parsers = self._parsers.get((settings.exchange, settings.market_type))
            consumer_task = self._consumer_tasks.get(key)
            parser_task_map = self._parser_tasks.get((settings.exchange, settings.market_type), {})

            # Ловим падение consumer-task сразу (event=task_exception), один раз на task
            if consumer_task is not None:
                tid = id(consumer_task)
                if tid not in self._task_exception_logged and consumer_task.done() and not consumer_task.cancelled():
                    exc = None
                    try:
                        exc = consumer_task.exception()
                    except Exception as e:  # pragma: no cover
                        exc = e
                    if exc is not None:
                        self._task_exception_logged.add(tid)
                        log_debug_event(
                            level="error",
                            screener_name=settings.name,
                            screener_id=settings.id,
                            exchange=str(settings.exchange.value),
                            market_type=str(settings.market_type.value),
                            event="task_exception",
                            symbol=None,
                            payload={
                                "kind": "consumer_task",
                                "task": self._task_state(consumer_task),
                            },
                            run_id=self._run_id,
                            cycle_id=self._monitor_cycle_id,
                            exc=exc,
                        )

            # Если consumer task внезапно завершился — логируем (с троттлом)
            if consumer_task is not None and consumer_task.done():
                last = self._last_task_done_log_ts.get(key, 0.0)
                if now - last >= self._STALE_LOG_THROTTLE_SEC:
                    self._last_task_done_log_ts[key] = now
                    log_debug_event(
                        level="error",
                        screener_name=settings.name,
                        screener_id=settings.id,
                        exchange=str(settings.exchange.value),
                        market_type=str(settings.market_type.value),
                        event="consumer_task_done",
                        symbol=None,
                        payload={
                            "consumer_task": self._task_state(consumer_task),
                        },
                        run_id=self._run_id,
                        cycle_id=self._monitor_cycle_id,
                    )

            if not parsers:
                continue

            def age(ts: float) -> float | None:
                return None if not ts else round(now - ts, 3)

            def effective_age(parser_obj) -> float:
                ts = getattr(parser_obj, "last_update_ts", 0.0) or getattr(
                    parser_obj, "started_ts", 0.0
                )
                return round(now - float(ts or now), 3)

            ages = {
                "agg_trades": effective_age(parsers.agg_trades),
                "ticker_daily": effective_age(parsers.ticker_daily),
                "open_interest": effective_age(parsers.open_interest) if parsers.open_interest else None,
                "funding_rate": effective_age(parsers.funding_rate) if parsers.funding_rate else None,
                "liquidations": effective_age(parsers.liquidations) if parsers.liquidations else None,
            }

            stale = {k: v for k, v in ages.items() if v is not None and v > self._STALE_THRESHOLD_SEC}
            if not stale:
                continue

            last = self._last_stale_log_ts.get(key, 0.0)
            if now - last < self._STALE_LOG_THROTTLE_SEC:
                continue
            self._last_stale_log_ts[key] = now

            log_debug_event(
                level="warning",
                screener_name=settings.name,
                screener_id=settings.id,
                exchange=str(settings.exchange.value),
                market_type=str(settings.market_type.value),
                event="stale_data",
                symbol=None,
                payload={
                    "threshold_sec": self._STALE_THRESHOLD_SEC,
                    "parsers_age_sec": ages,
                    "stale": stale,
                    "consumer_task": self._task_state(consumer_task),
                    "parser_tasks": {
                        name: self._task_state(t) for name, t in parser_task_map.items()
                    },
                    "websockets": self._websocket_state(parsers),
                },
                run_id=self._run_id,
                cycle_id=self._monitor_cycle_id,
            )

    async def stop(self) -> None:
        """Останавливает оператора и все запущенные процессы."""
        self._is_running = False

        #Останавливаем консьюмеров раньше парсеров, чтобы они не читали пустые данные
        await self._stop_consumers(list(self._consumers.keys()))
        await self._stop_parsers(list(self._parsers.keys()))

        log_signals_event(
            {
                "kind": "lifecycle",
                "action": "operator_stopped",
                "run_id": self._run_id,
            }
        )
        self._logger.info ("Operator stopped")

    async def _fetch_settings(self) -> list[SettingsDTO]:
        """Получает актуальные настройки скринера из базы данных.
        
        Returns:
            list[SettingsDTO]: Список включенных настроек.
        """
        async with Database.session_context() as db:
            settings_list = await db.settings_repo.get_all()

        # Оставляем только включенные настройки и переводим их в DTO
        enabled_settings = [settings for settings in settings_list if settings.enabled]
        return [SettingsDTO.model_validate(settings) for settings in enabled_settings]

    async def _update_parsers(self, settings_list: list[SettingsDTO]) -> None:
        """Создает и останавливает парсеры под актуальные настройки."""
        required_pairs = {(settings.exchange, settings.market_type) for settings in settings_list}

        # Запускаем парсеры для новых пар биржа+рынок
        for exchange, market_type in required_pairs:
            key = (exchange, market_type)
            if key in self._parsers:
                continue

            agg_trades = AggTradesParser(exchange=exchange, market_type=market_type)
            ticker_daily = TickerDailyParser(exchange=exchange, market_type=market_type)
            if market_type == MarketType.FUTURES:
                funding_rate = FundingRateParser(exchange=exchange, market_type=market_type)
                liquidations = LiquidationsParser(exchange=exchange, market_type=market_type)
                open_interest = OpenInterestParser(exchange=exchange, market_type=market_type)
            else:
                funding_rate = None
                liquidations = None
                open_interest = None
            parsers = ParsersDTO(
                agg_trades=agg_trades,
                ticker_daily=ticker_daily,
                funding_rate=funding_rate,
                liquidations=liquidations,
                open_interest=open_interest,
            )
            self._parsers[key] = parsers
            self._parser_tasks[key] = {
                name: asyncio.create_task(
                    start_fn(),
                    name=f"parser:{name}:{exchange.value}:{market_type.value}",
                )
                for name, start_fn in self._parser_task_factories(parsers).items()
            }
            self._logger.info (f"Parsers started for {exchange}:{market_type}")
            log_signals_event(
                {
                    "kind": "lifecycle",
                    "action": "parsers_pair_started",
                    "exchange": str(exchange.value),
                    "market_type": str(market_type.value),
                    "run_id": self._run_id,
                }
            )

        # Останавливаем парсеры, которые больше не нужны
        pairs_to_stop = set(self._parsers.keys()) - required_pairs
        if pairs_to_stop:
            await self._stop_parsers(list(pairs_to_stop))

    async def _update_consumers(self, settings_list: list[SettingsDTO]) -> None:
        """Создает, обновляет и останавливает консьюмеров под актуальные настройки."""
        # Создаем или обновляем консьюмеров
        for settings in settings_list:
            key = (settings.id, settings.exchange, settings.market_type)
            existing_consumer = self._consumers.get(key)

            if existing_consumer:
                existing_consumer.update_settings(settings)
                continue

            parsers = self._parsers.get((settings.exchange, settings.market_type))
            if not parsers:
                self._logger.warning(
                    f"Parsers is not ready {settings.exchange}:{settings.market_type}"
                )
                continue

            consumer = Consumer(parsers=parsers, settings=settings)
            self._consumers[key] = consumer
            self._consumer_tasks[key] = asyncio.create_task(consumer.start())

            self._logger.info (
                f"consumer started for settings_id={settings.id} "
                f"{settings.exchange}: {settings.market_type})"
            )
            log_signals_event(
                {
                    "kind": "lifecycle",
                    "action": "screener_consumer_started",
                    "screener_id": settings.id,
                    "screener_name": settings.name,
                    "exchange": str(settings.exchange.value),
                    "market_type": str(settings.market_type.value),
                    "run_id": self._run_id,
                }
            )

        # Останавливаем консьюмеров, которые больше не нужны
        desired_keys = {
            (settings.id, settings.exchange, settings.market_type) for settings in settings_list
        }
        keys_to_stop = set(self._consumers.keys()) - desired_keys
        if keys_to_stop:
            await self._stop_consumers(list(keys_to_stop))

    async def _stop_parsers(self, keys: list[tuple[Exchange, MarketType]]) -> None:
        """Останавливает парсеры и связанные с ними задачи.

        Сначала вызываем parser.stop() (закрытие вебсокетов и отмена _worker),
        затем отменяем задачи, в которых крутился parser.start().
        Так не остаётся pending Task при уничтожении.
        """
        stop_tasks: list[Awaitable[None]] = []
        tasks_to_cancel: list[asyncio.Task] = []

        for key in keys:
            parsers = self._parsers.pop(key, None)
            if parsers:
                stop_tasks.extend(
                    [
                        parsers.agg_trades.stop(),
                        parsers.funding_rate.stop() if parsers.funding_rate else asyncio.sleep(0),
                        parsers.liquidations.stop() if parsers.liquidations else asyncio.sleep(0),
                        parsers.open_interest.stop() if parsers.open_interest else asyncio.sleep(0),
                        parsers.ticker_daily.stop(),
                    ]
                )

            for task in self._parser_tasks.pop(key, {}).values():
                tasks_to_cancel.append(task)

            self._logger.info (f"Parser stopped for {key[0]}:{key[1]}")
            log_signals_event(
                {
                    "kind": "lifecycle",
                    "action": "parsers_pair_stopped",
                    "exchange": str(key[0].value),
                    "market_type": str(key[1].value),
                    "run_id": self._run_id,
                }
            )

        # Сначала останавливаем вебсокеты (в т.ч. отмена _worker), потом отменяем задачи парсеров
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        for task in tasks_to_cancel:
            if not task.done():
                task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    async def _stop_consumers(self, keys: list[tuple[int, Exchange, MarketType]]) -> None:
        """Останавливает консьюмеров и связанные с ними задачи. Сначала stop(), затем отмена задач."""
        stop_tasks: list[Awaitable[None]] = []
        tasks_to_cancel: list[asyncio.Task] = []

        for key in keys:
            consumer = self._consumers.pop(key, None)
            screener_name = consumer.settings.name if consumer else None
            if consumer:
                stop_tasks.append(consumer.stop())

            task = self._consumer_tasks.pop(key, None)
            if task:
                tasks_to_cancel.append(task)

            self._logger.info (f"Consumer stopped for settings_id={key[0]}")
            log_signals_event(
                {
                    "kind": "lifecycle",
                    "action": "screener_consumer_stopped",
                    "screener_id": key[0],
                    "screener_name": screener_name,
                    "exchange": str(key[1].value),
                    "market_type": str(key[2].value),
                    "run_id": self._run_id,
                }
            )

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        for task in tasks_to_cancel:
            if not task.done():
                task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)