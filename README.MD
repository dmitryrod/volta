# Money Pulso

Единая **панель скрининга крипторынка**: правила отбора инструментов, поток сигналов и аналитика сессий Scanner — без отдельных скриптов для каждого сценария.

[![Python 3.13+](https://img.shields.io/static/v1?label=Python&message=3.13%2B&color=3776AB&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/static/v1?label=FastAPI&message=framework&color=009688&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/static/v1?label=PostgreSQL&message=data&color=4169E1&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Starlette Admin](https://img.shields.io/static/v1?label=Starlette&message=Admin&color=5865F2)](https://jowilf.github.io/starlette-admin/)
[![Docker](https://img.shields.io/static/v1?label=Docker&message=compose&color=2496ED&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

## Зачем это нужно

- Отбор пар по настраиваемым фильтрам в скринерах (деривативы: открытый интерес, фандинг, ликвидации и др.).
- Уведомления о срабатываниях в **Telegram** и журнал в **PostgreSQL**.
- **Веб-админка**: скринеры, карточки сигналов в реальном времени, мониторинг и **аналитика Scanner** с переходом к статистике по символу.
- Фоновые задачи без ручного опроса биржевых API в интерфейсе. Не требуются API ключи криптобирж.

## Скриншоты интерфейса

### Обзор

![Обзор и метрики панели](app/assets/readme/overview.png)

Дашборд со сводкой по системе, скринерам, сигналам и сессиям Scanner.

### Скринеры

![Список скринеров](app/assets/readme/screeners.jpg)

Управление правилами и параметрами подключённых скринеров.

### Сигналы

![Карточки сигналов](app/assets/readme/signals.png)

Поток срабатываний на основе активных фильтров.

### Аналитика Scanner

![Каталог tracking-сессий](app/assets/readme/analytics.png)

Таблица сессий с переходом к подробному графику по символу.

### Статистика по символу

![График Score и фильтров по сессии](app/assets/readme/stat-symbol.jpg)

Страница статистики: временные ряды score и фильтров поверх диапазона цены по минутным бакетам.

## Быстрый старт

Из каталога **`app/`** (рядом с `docker-compose.yaml`):

```bash
docker compose up --build
```

Остановка: `docker compose down`. Переменные окружения — файл **`.env`** в `app/`; описание переменных — **[`.env.example`](.env.example)**

После запуска: **`http://localhost:8000/admin/`**

## Безопасность

- Секреты (боты, БД, ключ подписи сессии) задаются только через окружение; реальные значения не коммитить.
- Публичный репозиторий не заменяет модель угроз продакшена: ограничивайте доступ к админке и БД на сетевом уровне.

## Отказ от ответственности

Сигналы и данные в интерфейсе — **не инвестиционная рекомендация**, а техническое уведомление о выполнении настроенных вами правил. Решения по рискам принимаете вы.

## Лицензия

В корне репозитория файл лицензии может отсутствовать — условия использования уточняйте у владельца проекта.

## Миграции БД

В контейнере при старте выполняется `alembic upgrade head`. Локально из `app/`: `uv run alembic upgrade head`.
