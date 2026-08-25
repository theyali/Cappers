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
docker compose up --build
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
