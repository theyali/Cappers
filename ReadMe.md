# Cappers

Каркас Django-проекта для спортивной аналитики и пользовательских прогнозов.

## Stack

- Django
- PostgreSQL 16
- PgBouncer
- Redis
- Celery
- Celery Beat
- Uvicorn (production)

## Local start

```bash
cp .env.example .env
docker compose up --build -d
```

При `DEBUG=True` контейнер `web` запускает Django `runserver`.

При `DEBUG=False` контейнер выполняет `collectstatic` и запускает ASGI через Uvicorn.

Проверка:

```bash
curl http://localhost:8000/health/
```

Админка:

```bash
docker compose exec web python manage.py createsuperuser
```

## Database access

Внутри Docker Django подключается к `pgbouncer:6432`.

С хоста PgBouncer доступен на `localhost:6433`.

Прямой PostgreSQL наружу не опубликован.

## Управление контейнерами без `-p`

В `docker-compose.yml` закреплено `name: cappershub`. Ручные команды и
`deploy/deploy.sh` используют одно имя независимо от имени каталога. Команды
ниже выполняются из корня проекта после обновления файлов на сервере:

```bash
docker compose ps
docker compose restart web celery celery-beat
docker compose restart neurokeff-live neurokeff-odds
docker compose logs --tail=50 -f neurokeff-odds
```

`restart` только перезапускает существующие контейнеры: он не создаёт отсутствующий
сервис, не пересобирает образ и не применяет изменения `.env`/Compose. Для этого:

```bash
docker compose up -d --no-deps --force-recreate web celery celery-beat
docker compose up -d --no-deps --build neurokeff-odds
```

Явно указанный `neurokeff-odds` можно запустить без `--profile live`; обычный
`docker compose up -d` без имени сервиса WS-процессы не включает. При деплое
через GitHub Actions оба WS-сервиса поднимает `DEPLOY_LIVE_WS=1`.

`COMPOSE_PROJECT_NAME` в окружении или `.env` имеет приоритет над `name:`.
На сервере с существующим стеком `cappershub` оставьте его незаданным либо равным
`cappershub`. Если локальные контейнеры уже созданы как `cappers-*`, один раз
добавьте в **локальный** `.env` `COMPOSE_PROJECT_NAME=cappers`: тогда и ручные
команды, и deploy сохранят прежний стек без `-p`. Не создавайте новый стек под
другим именем вместо существующего. Смена имени не переносит контейнеры и volumes.

Подробности потоков и проверок — [deploy/NEUROKEFF_LIVE.md](deploy/NEUROKEFF_LIVE.md).
