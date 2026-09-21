"""Настройка админ-панели и регистрация представлений."""

__all__ = [
    "register_admin_routes",
    "signal_orm_row_to_dict",
    "parse_signals_log_line",
    "dedupe_signal_log_items_newest_first",
]

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from sqlalchemy import delete, desc, func, select, update
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette_admin import I18nConfig
from starlette_admin.contrib.sqla import Admin

from app.config import config
from app.database import Database, SettingsORM, SignalORM
from app.schemas import EnvironmentType
from app.database.models import ScannerRuntimeSettingsORM, TrackingSessionORM
from app.screener import scanner_runtime
from app.screener.statistics_store import purge_statistics_data_files
from app.test_signal_broadcast import (
    register_test_stream_subscriber,
    unregister_test_stream_subscriber,
)
from app.utils.coinmarketcap_rank import get_cmc_rank_for_symbol

from .auth import AdminAuthProvider
from .roles import DEMO_SCANNER_RUNTIME_RESPONSE, ensure_full_admin, is_demo_session
from .dashboard_summary import build_dashboard_summary
from .monitoring_metrics import get_payload, record_snapshot
from .pg_counts import signals_total_for_list_ui
from .view import (
    AnalyticsCatalogView,
    DashboardCustomView,
    LogsViewerView,
    MetrCustomView,
    SettingsModelView,
    SignalsView,
    UiSettingsView,
)

_SIGNALS_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "signals_log.txt"
_APP_DIR = Path(__file__).resolve().parents[1]
# Абсолютный путь: относительный "app/admin/templates" ломается при cwd внутри app/ (TemplateNotFound).
_ADMIN_TEMPLATES_DIR = str(Path(__file__).resolve().parent / "templates")
_TIMEZONE_UI_JS_PATH = Path(__file__).resolve().parent / "timezone_ui.js"


def signal_orm_row_to_dict(row: SignalORM) -> dict:
    """Сериализация строки `signals` для API `/admin_api/signals` и SSE."""
    live_rank = get_cmc_rank_for_symbol(row.symbol)
    card_snapshot = None
    raw_snap = getattr(row, "card_snapshot_json", None)
    if raw_snap:
        try:
            card_snapshot = json.loads(raw_snap)
        except (json.JSONDecodeError, TypeError):
            card_snapshot = None
    tid = getattr(row, "tracking_id", None)
    stat_href = scanner_runtime.stat_url_path(row.symbol, tid) if tid else None
    has_snap = bool(card_snapshot and isinstance(card_snapshot, dict))
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "screener_name": row.screener_name,
        "screener_id": row.screener_id,
        "exchange": row.exchange,
        "market_type": row.market_type,
        "symbol": row.symbol,
        "telegram_text": row.telegram_text,
        "telegram_ok": row.telegram_ok,
        "error": row.error,
        "cmc_rank": live_rank,
        "tracking_id": tid,
        "stat_href": stat_href,
        "card_snapshot": card_snapshot,
        "render_as_scanner": has_snap,
    }


def dedupe_signal_log_items_newest_first(items: list[dict]) -> list[dict]:
    """Убирает повторы одной Scanner-сессии в ленте лог-файла.

    После ``items.reverse()`` в `_read_file_signals` порядок — от новых к старым.
    Для строк с непустым ``tracking_id`` оставляем только первую (самую новую)
    для пары (tracking_id, symbol, exchange, market_type). Без ``tracking_id``
    каждая строка считается отдельным событием (как в legacy-логах).

    Args:
        items: Список dict из ``parse_signals_log_line`` (уже в порядке новые первые).

    Returns:
        Отфильтрованный список той же структуры.
    """
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict] = []
    for it in items:
        tid = it.get("tracking_id")
        if isinstance(tid, str) and tid.strip():
            key = (
                tid.strip(),
                str(it.get("symbol") or ""),
                str(it.get("exchange") or ""),
                str(it.get("market_type") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
        out.append(it)
    return out


def parse_signals_log_line(line: str) -> dict | None:
    """Парсит строку из ``signals_log.txt``. Возвращает dict для API/SSE или ``None``.

    Поля ``card_snapshot``, ``tracking_id``, ``stat_href``, ``render_as_scanner`` —
    если в JSON записан снимок Scanner (паритет с ``signal_orm_row_to_dict`` для БД).
    """
    line = line.strip()
    if not line:
        return None
    try:
        tab_idx = line.index("\t")
        ts = line[:tab_idx]
        payload = json.loads(line[tab_idx + 1 :])
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("kind") != "signal":
        return None
    symbol = payload.get("symbol", "")
    live_rank = get_cmc_rank_for_symbol(symbol)
    card_snapshot = None
    raw_snap = payload.get("card_snapshot")
    if raw_snap is not None:
        if isinstance(raw_snap, str):
            try:
                card_snapshot = json.loads(raw_snap)
            except (json.JSONDecodeError, TypeError):
                card_snapshot = None
        elif isinstance(raw_snap, dict):
            card_snapshot = raw_snap
    tid = payload.get("tracking_id")
    if not tid or not isinstance(tid, str):
        tid = None
    stat_href = scanner_runtime.stat_url_path(symbol, tid) if tid else None
    has_snap = bool(
        card_snapshot
        and isinstance(card_snapshot, dict)
        and len(card_snapshot) > 0
    )
    return {
        "id": ts,
        "created_at": payload.get("ts_moscow") or ts,
        "screener_name": payload.get("screener_name", ""),
        "screener_id": payload.get("screener_id", 0),
        "exchange": payload.get("exchange", ""),
        "market_type": payload.get("market_type", ""),
        "symbol": symbol,
        "telegram_text": (payload.get("telegram_text") or "").replace("\\n", "\n"),
        "telegram_ok": bool(payload.get("telegram_ok", False)),
        "error": payload.get("error"),
        "cmc_rank": live_rank,
        "tracking_id": tid,
        "stat_href": stat_href,
        "card_snapshot": card_snapshot,
        "render_as_scanner": has_snap,
    }


async def _signals_total_for_pagination(db: Database) -> int:
    """Число строк signals для UI пагинации: сначала быстрая оценка из pg_stat (PostgreSQL)."""
    return await signals_total_for_list_ui(db.session)


def register_admin_routes(app: FastAPI) -> None:
    """Регистрирует представления админ-панели в FastAPI-приложении."""

    @app.get("/admin_api/screeners/global-debug")
    async def _get_global_debug() -> JSONResponse:
        async with Database.session_context() as db:
            total = await db.session.scalar(select(func.count()).select_from(SettingsORM))
            enabled_count = await db.session.scalar(
                select(func.count())
                .select_from(SettingsORM)
                .where(SettingsORM.debug.is_(True))
            )
        total_i = int(total or 0)
        enabled_i = int(enabled_count or 0)
        return JSONResponse(
            {
                "total": total_i,
                "enabled_count": enabled_i,
                "all_enabled": total_i > 0 and enabled_i == total_i,
                "any_enabled": enabled_i > 0,
            }
        )

    @app.post("/admin_api/screeners/global-debug")
    async def _set_global_debug(request: Request, enabled: bool) -> JSONResponse:
        ensure_full_admin(request)
        async with Database.session_context() as db:
            await db.session.execute(update(SettingsORM).values(debug=enabled))
            await db.commit()
            total = await db.session.scalar(select(func.count()).select_from(SettingsORM))
        return JSONResponse({"ok": True, "enabled": enabled, "total": int(total or 0)})

    @app.get("/admin_api/screeners/global-debug.js")
    async def _global_debug_js(request: Request) -> Response:
        demo_js = "true" if is_demo_session(request) else "false"
        js = (
            "window.__MP_ADMIN_SCREENERS_DEMO__ = "
            + demo_js
            + ";\n"
            + r"""
(() => {
  const STATE_URL = '/admin_api/screeners/global-debug';

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) node.setAttribute(k, String(v));
    }
    for (const child of children) node.append(child);
    return node;
  }

  function findMountPoint() {
    // Идеальный вариант: вставиться рядом с кнопкой "Добавить Скринер"
    const addBtn = document.querySelector('a.btn.btn-primary, a.btn.btn-primary[href*="/admin/screeners/create"]');
    if (addBtn && addBtn.parentElement) return { type: 'after-button', button: addBtn, container: addBtn.parentElement };

    // Фолбэк: правая часть заголовка карточки списка
    const cardHeader = document.querySelector('.card .card-header, .content .card-header');
    if (cardHeader) return { type: 'append', container: cardHeader };

    const pageHeader = document.querySelector('.page-header');
    if (pageHeader) return { type: 'append', container: pageHeader };

    return { type: 'append', container: document.body };
  }

  async function fetchState() {
    const res = await fetch(STATE_URL, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('state fetch failed');
    return await res.json();
  }

  async function setState(enabled) {
    const url = `${STATE_URL}?enabled=${enabled ? 'true' : 'false'}`;
    const res = await fetch(url, { method: 'POST', credentials: 'same-origin' });
    if (!res.ok) throw new Error('state set failed');
    return await res.json();
  }

  function renderToggle(mount) {
    const wrapper = el('div', {
      class: 'mp-global-debug-toggle d-flex flex-column flex-md-row align-items-stretch align-items-md-center gap-2 flex-wrap flex-md-nowrap',
      style: 'min-width:0; max-width:100%;',
    });

    const switchWrap = el('label', { class: 'form-check form-switch m-0 align-self-start align-self-md-center' });
    const input = el('input', { class: 'form-check-input', type: 'checkbox', id: 'global-debug-toggle' });
    const label = el('span', { class: 'form-check-label text-break', text: 'Глобальный режим отладки' });
    switchWrap.append(input, label);

    const status = el('div', {
      class: 'text-secondary small flex-grow-1 text-break',
      id: 'global-debug-status',
      style: 'min-width:0; white-space:normal;',
      text: '',
    });

    wrapper.append(switchWrap, status);

    if (mount?.type === 'after-button' && mount.button?.parentElement) {
      mount.button.insertAdjacentElement('beforebegin', wrapper);
    } else {
      mount.container.append(wrapper);
    }

    const setUI = (state) => {
      const { total, enabled_count, all_enabled, any_enabled } = state || {};
      input.indeterminate = Boolean(any_enabled && !all_enabled);
      input.checked = Boolean(all_enabled);
      const tail = total ? `${enabled_count}/${total}` : '0/0';
      status.textContent = input.indeterminate
        ? `Смешанный режим: включено ${tail}`
        : (input.checked ? `Включено ${tail}` : `Выключено ${tail}`);
    };

    const setLoading = (loading) => {
      if (window.__MP_ADMIN_SCREENERS_DEMO__) {
        input.disabled = true;
        status.setAttribute('data-loading', loading ? 'true' : 'false');
        return;
      }
      input.disabled = loading;
      status.setAttribute('data-loading', loading ? 'true' : 'false');
    };

    let lastState = null;
    setLoading(true);
    fetchState()
      .then((s) => { lastState = s; setUI(s); })
      .catch(() => { status.textContent = 'Не удалось получить состояние.'; })
      .finally(() => setLoading(false));

    input.addEventListener('change', async () => {
      if (window.__MP_ADMIN_SCREENERS_DEMO__) {
        if (lastState) setUI(lastState);
        return;
      }
      const enabled = input.checked;
      setLoading(true);
      try {
        await setState(enabled);
        const s = await fetchState();
        lastState = s;
        setUI(s);
        window.location.reload();
      } catch (e) {
        if (lastState) setUI(lastState);
        status.textContent = 'Ошибка применения. Попробуйте ещё раз.';
      } finally {
        setLoading(false);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!/\/admin\/screeners\/list\/?$/.test(window.location.pathname)) return;
    const mount = findMountPoint();
    renderToggle(mount);
  });
})();
"""
        )
        return Response(content=js, media_type="application/javascript; charset=utf-8")

    @app.get("/admin_api/ui/timezone.js")
    async def _timezone_ui_js() -> Response:
        """Общий модуль: форматирование времени в выбранной IANA-зоне (localStorage)."""
        body = _TIMEZONE_UI_JS_PATH.read_text(encoding="utf-8")
        return Response(content=body, media_type="application/javascript; charset=utf-8")

    @app.get("/admin_api/monitoring/metrics")
    async def _get_monitoring_metrics() -> JSONResponse:
        """JSON для страницы «Система»: psutil + in-memory ряды; размер `app/` не чаще 1/мин."""
        await asyncio.to_thread(record_snapshot)
        return JSONResponse(get_payload())

    @app.get("/admin_api/dashboard/summary")
    async def _admin_dashboard_summary() -> JSONResponse:
        """Сводка для главной админки и опционального автообновления виджетов."""
        data = await build_dashboard_summary()
        return JSONResponse(data)

    admin = Admin(
        engine=Database.engine,
        base_url="/admin",
        templates_dir=_ADMIN_TEMPLATES_DIR,
        auth_provider=AdminAuthProvider(),
        login_logo_url=config.admin.logo_url,
        i18n_config=I18nConfig(default_locale="ru"),
        middlewares=[],
        index_view=DashboardCustomView(),
    )
    # В production — noindex в шаблоне; в development Lighthouse не штрафует за «blocked from indexing».
    admin.templates.env.globals["admin_robots_noindex"] = (
        config.environment == EnvironmentType.PRODUCTION
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Signals API
    # ──────────────────────────────────────────────────────────────────────────

    def _read_file_signals() -> list[dict]:
        """Читает все сигналы из signals_log.txt. Новые — в начале."""
        if not _SIGNALS_LOG_PATH.exists():
            return []
        items: list[dict] = []
        try:
            with _SIGNALS_LOG_PATH.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parsed = parse_signals_log_line(line)
                    if parsed:
                        items.append(parsed)
        except OSError:
            return []
        items.reverse()
        return dedupe_signal_log_items_newest_first(items)

    @app.get("/admin_api/signals")
    async def _get_signals(
        request: Request,
        source: str = "db",
        page: int = 1,
        per_page: int = 100,
    ) -> JSONResponse:
        page = max(1, page)
        per_page = per_page if per_page in (100, 500, 1000) else 100
        offset = (page - 1) * per_page

        if source == "file":
            all_items = await asyncio.to_thread(_read_file_signals)
            total = len(all_items)
            items = all_items[offset: offset + per_page]
            return JSONResponse({
                "items": items,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": max(1, math.ceil(total / per_page)),
                "source": "file",
            })

        if source == "test":
            return JSONResponse({
                "items": [],
                "total": 0,
                "page": 1,
                "per_page": per_page,
                "pages": 1,
                "source": "test",
            })

        # source == "db"
        async with Database.session_context() as db:
            total = await _signals_total_for_pagination(db)
            rows = (
                await db.session.execute(
                    select(SignalORM)
                    .order_by(SignalORM.id.desc())
                    .limit(per_page)
                    .offset(offset)
                )
            ).scalars().all()
        return JSONResponse({
            "items": [signal_orm_row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, math.ceil(total / per_page)),
            "source": "db",
        })

    @app.post("/admin_api/signals/purge")
    async def _purge_signals(
        request: Request,
        target: str = Query(..., description="db — только таблица signals; log — только signals_log.txt"),
    ) -> JSONResponse:
        """Очистка по выбору: только БД или только лог-файл сигналов."""
        ensure_full_admin(request)
        t = (target or "").strip().lower()
        if t == "db":
            deleted = 0
            try:
                async with Database.session_context() as db:
                    cnt = await db.session.scalar(
                        select(func.count()).select_from(SignalORM)
                    )
                    deleted = int(cnt or 0)
                    await db.session.execute(delete(SignalORM))
                    await db.commit()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return JSONResponse({"ok": True, "signals_deleted": deleted})
        if t == "log":
            try:
                _SIGNALS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                _SIGNALS_LOG_PATH.write_text("", encoding="utf-8")
            except OSError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return JSONResponse({"ok": True, "log_cleared": True})
        raise HTTPException(
            status_code=400,
            detail="target must be 'db' or 'log'",
        )

    @app.get("/admin_api/signals/stream")
    async def _stream_signals(
        request: Request,
        source: str = "db",
    ) -> StreamingResponse:
        """SSE-стрим новых сигналов. source=db|file|test."""

        async def _test_generator() -> AsyncGenerator[str, None]:
            q: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)
            register_test_stream_subscriber(q)
            ping_counter = 0
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(q.get(), timeout=0.3)
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                        continue
                    except asyncio.TimeoutError:
                        pass
                    ping_counter += 1
                    if ping_counter >= 50:
                        yield "event: ping\ndata: {}\n\n"
                        ping_counter = 0
            finally:
                unregister_test_stream_subscriber(q)

        async def _db_generator() -> AsyncGenerator[str, None]:
            last_id: int = 0
            # Получаем текущий максимальный id как стартовую точку
            async with Database.session_context() as db:
                max_id = await db.session.scalar(
                    select(func.max(SignalORM.id))
                )
                last_id = int(max_id or 0)

            ping_counter = 0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    async with Database.session_context() as db:
                        rows = (
                            await db.session.execute(
                                select(SignalORM)
                                .where(SignalORM.id > last_id)
                                .order_by(SignalORM.id.asc())
                                .limit(50)
                            )
                        ).scalars().all()
                    for row in rows:
                        last_id = row.id
                        yield f"data: {json.dumps(signal_orm_row_to_dict(row), ensure_ascii=False)}\n\n"
                except Exception:
                    pass
                ping_counter += 1
                if ping_counter >= 50:  # каждые ~15 сек
                    yield "event: ping\ndata: {}\n\n"
                    ping_counter = 0
                await asyncio.sleep(0.3)

        async def _file_generator() -> AsyncGenerator[str, None]:
            file_pos: int = 0
            if _SIGNALS_LOG_PATH.exists():
                file_pos = _SIGNALS_LOG_PATH.stat().st_size

            ping_counter = 0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    if _SIGNALS_LOG_PATH.exists():
                        current_size = _SIGNALS_LOG_PATH.stat().st_size
                        if current_size > file_pos:
                            with _SIGNALS_LOG_PATH.open("rb") as fh:
                                fh.seek(file_pos)
                                new_bytes = fh.read(current_size - file_pos)
                            file_pos = current_size
                            for raw_line in new_bytes.decode("utf-8", errors="replace").splitlines():
                                parsed = parse_signals_log_line(raw_line)
                                if parsed:
                                    yield f"data: {json.dumps(parsed, ensure_ascii=False)}\n\n"
                        elif current_size < file_pos:
                            # Файл был ротирован
                            file_pos = current_size
                except Exception:
                    pass
                ping_counter += 1
                if ping_counter >= 50:
                    yield "event: ping\ndata: {}\n\n"
                    ping_counter = 0
                await asyncio.sleep(0.3)

        if source == "test":
            generator = _test_generator()
        else:
            generator = _db_generator() if source != "file" else _file_generator()
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Scanner runtime + Analytics API
    # ──────────────────────────────────────────────────────────────────────────

    @app.get("/admin_api/scanner/runtime-settings")
    async def _get_scanner_runtime_settings_api(request: Request) -> JSONResponse:
        if is_demo_session(request):
            return JSONResponse(dict(DEMO_SCANNER_RUNTIME_RESPONSE))
        async with Database.session_context() as db:
            row = await db.session.get(ScannerRuntimeSettingsORM, 1)
            if row is None:
                row = ScannerRuntimeSettingsORM(
                    id=1,
                    max_cards=10,
                    posttracking_minutes=30,
                    cooldown_hours=24,
                    statistics_enabled=True,
                )
                db.session.add(row)
                await db.commit()
                await db.session.refresh(row)
        return JSONResponse(
            {
                "max_cards": row.max_cards,
                "posttracking_minutes": row.posttracking_minutes,
                "cooldown_hours": row.cooldown_hours,
                "statistics_enabled": row.statistics_enabled,
            }
        )

    @app.post("/admin_api/scanner/runtime-settings")
    async def _post_scanner_runtime_settings_api(
        request: Request,
        max_cards: int | None = Query(None),
        posttracking_minutes: int | None = Query(None),
        cooldown_hours: int | None = Query(None),
        statistics_enabled: bool | None = Query(None),
    ) -> JSONResponse:
        ensure_full_admin(request)
        async with Database.session_context() as db:
            row = await db.session.get(ScannerRuntimeSettingsORM, 1)
            if row is None:
                row = ScannerRuntimeSettingsORM(
                    id=1,
                    max_cards=10,
                    posttracking_minutes=30,
                    cooldown_hours=24,
                    statistics_enabled=True,
                )
                db.session.add(row)
            if max_cards is not None:
                row.max_cards = max(1, min(200, int(max_cards)))
            if posttracking_minutes is not None:
                row.posttracking_minutes = max(0, int(posttracking_minutes))
            if cooldown_hours is not None:
                row.cooldown_hours = max(0, int(cooldown_hours))
            if statistics_enabled is not None:
                row.statistics_enabled = bool(statistics_enabled)
            await db.commit()
            await db.session.refresh(row)
        scanner_runtime.bump_cache_refresh()
        return JSONResponse(
            {
                "max_cards": row.max_cards,
                "posttracking_minutes": row.posttracking_minutes,
                "cooldown_hours": row.cooldown_hours,
                "statistics_enabled": row.statistics_enabled,
            }
        )

    @app.post("/admin_api/scanner/close")
    async def _scanner_close(tracking_id: str = Query(...)) -> JSONResponse:
        async with Database.session_context() as db:
            row = await db.session.get(TrackingSessionORM, tracking_id)
            if row is None:
                return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
            scanner_runtime.request_manual_close(tracking_id, row.screener_id, row.symbol)
            row.status = "closed"
            row.closed_at = datetime.now(timezone.utc)
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        return JSONResponse({"ok": True})

    def _read_jsonl_file(rel_path: str) -> list[dict]:
        path = _APP_DIR / rel_path.replace("/", os.sep)
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return out

    @app.get("/admin_api/analytics/sessions")
    async def _analytics_sessions_api() -> JSONResponse:
        async with Database.session_context() as db:
            rows = (
                await db.session.execute(
                    select(TrackingSessionORM).order_by(
                        desc(TrackingSessionORM.created_at)
                    ).limit(500)
                )
            ).scalars().all()
        items = []
        for r in rows:
            if r.status in ("triggered", "active", "posttracking"):
                cat = "active"
            elif r.status in ("completed", "closed"):
                cat = "completed"
            else:
                cat = "other"
            items.append(
                {
                    "tracking_id": r.tracking_id,
                    "symbol": r.symbol,
                    "screener_name": r.screener_name,
                    "screener_id": r.screener_id,
                    "exchange": r.exchange,
                    "market_type": r.market_type,
                    "status": r.status,
                    "category": cat,
                    "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
                    "statistics_file_path": r.statistics_file_path,
                }
            )
        return JSONResponse({"items": items})

    @app.post("/admin_api/analytics/purge")
    async def _analytics_purge_all() -> JSONResponse:
        """Полная очистка аналитики Scanner: таблица ``tracking_sessions`` и файлы ``statistics-data``."""
        deleted_rows = 0
        try:
            async with Database.session_context() as db:
                cnt = await db.session.scalar(
                    select(func.count()).select_from(TrackingSessionORM)
                )
                deleted_rows = int(cnt or 0)
                await db.session.execute(delete(TrackingSessionORM))
                await db.commit()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        try:
            files_n = await asyncio.to_thread(purge_statistics_data_files)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        scanner_runtime.reset_statistics_runtime_state()
        scanner_runtime.bump_cache_refresh()
        return JSONResponse(
            {
                "ok": True,
                "tracking_sessions_deleted": deleted_rows,
                "files_deleted": files_n,
            }
        )

    @app.get("/admin_api/analytics/samples")
    async def _analytics_samples_api(tracking_id: str = Query(...)) -> JSONResponse:
        async with Database.session_context() as db:
            row = await db.session.get(TrackingSessionORM, tracking_id)
            if row is None:
                return JSONResponse(
                    {"samples": [], "session": None}, status_code=404
                )
            samples: list[dict] = []
            if row.statistics_file_path:
                samples = _read_jsonl_file(row.statistics_file_path)
        return JSONResponse(
            {
                "session": {
                    "tracking_id": tracking_id,
                    "status": row.status,
                    "symbol": row.symbol,
                    "exchange": row.exchange,
                },
                "samples": samples,
            }
        )

    async def _admin_analytics_stat_subpage(request: Request) -> Response:
        """Страница stat-* внутри смонтированного ``/admin`` (см. ``Admin.mount_to``)."""
        page = request.path_params.get("page") or ""
        parsed = scanner_runtime.parse_stat_page_path(page)
        if parsed is None:
            raise HTTPException(status_code=404)
        sym_slug, tid = parsed
        return admin.templates.TemplateResponse(
            request,
            "analytics_stat.html",
            {
                "request": request,
                "symbol_slug": sym_slug,
                "tracking_id": tid,
            },
        )

    # Регистрируем до mount_to: запросы к /admin/* обрабатывает подприложение admin, не корневой app.
    admin.routes.insert(
        0,
        Route(
            "/analytics/{page:path}",
            endpoint=_admin_analytics_stat_subpage,
            methods=["GET"],
            name="analytics_stat_subpage",
        ),
    )

    admin.add_view(SettingsModelView(model=SettingsORM, label="Скринеры", icon="fa fa-cogs"))
    admin.add_view(SignalsView(label="Сигналы", path="/signals", icon="fa fa-bell"))
    admin.add_view(
        AnalyticsCatalogView(label="Аналитика", path="/analytics", icon="fa fa-chart-line")
    )
    admin.add_view(MetrCustomView(label="Система", path="/monitoring", icon="fa fa-heartbeat"))
    admin.add_view(LogsViewerView(label="Логи", path="/logs", icon="fa fa-book"))
    admin.add_view(
        UiSettingsView(label="Настройки", path="/settings", icon="fa fa-sliders-h")
    )

    admin.mount_to(app)