# Cappers

Каркас Django-проекта для спортивной аналитики и пользовательских прогнозов.

## Контент юридических документов

Правила, конфиденциальность, соглашение и cookie используют поля и разделы
в **SEO → SEO страниц**. Включение «Использовать дизайн документа» переключает
страницу на общий адаптивный шаблон. Содержание строится из активных разделов
в заданном порядке; текст, таблицы и примечания редактируются внутри разделов.

После применения миграций заполнение из HTML-макетов запускается вручную:

```bash
docker compose exec web python manage.py seed_legal_documents --dry-run
docker compose exec web python manage.py seed_legal_documents
```

Сидер ищет правила по `front:rules`, а остальные документы — по
`front:static_page` и точным путям `/pages/privacy-policy/`,
`/pages/user-agreement/`, `/pages/cookie-policy/`. У правил также поддерживается
существующая SEO-запись с точным путём `/rules/`. Соглашение получает текущий
текст StaticPage; нового юридического текста для него сидер не сочиняет.

Повторный запуск сохраняет заполненные документы. `--force` заново заполняет
контент документов из макетов, сохраняя SEO-поля и загруженный PDF.
`--support-email=help@example.com` задаёт адрес кнопки поддержки; по умолчанию
используется email футера или `SUPPORT_EMAIL`. Данные макетов находятся в
`pages/seed_data/legal_documents.json`, стили — в общих `main.css` и `mobile.css`.
PDF загружается в SEO-запись: без файла кнопка скачивания скрыта.

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

Обычный деплой кода и шаблонов использует готовые образы: после миграций скрипт
пересоздаёт контейнеры приложения и включённые WS-сервисы без сборки. Сборка
выполняется один раз при `DEPLOY_BUILD=1` или `DEPLOY_FULL_RECREATE=1`.
Workflow включает её при изменениях файлов сборки или полном деплое.
Успешная версия хранится в `.git/cappers-deployed-revision` после проверки
готовности сервисов. Отменённый или неуспешный деплой не меняет эту отметку.
При её отсутствии следующий запуск выполняет полный деплой один раз.
Запуски production-деплоя выполняются последовательно, каждый применяет свой коммит.

`COMPOSE_PROJECT_NAME` в окружении или `.env` имеет приоритет над `name:`.
На сервере с существующим стеком `cappershub` оставьте его незаданным либо равным
`cappershub`. Если локальные контейнеры уже созданы как `cappers-*`, один раз
добавьте в **локальный** `.env` `COMPOSE_PROJECT_NAME=cappers`: тогда и ручные
команды, и deploy сохранят прежний стек без `-p`. Не создавайте новый стек под
другим именем вместо существующего. Смена имени не переносит контейнеры и volumes.

Подробности потоков и проверок — [deploy/NEUROKEFF_LIVE.md](deploy/NEUROKEFF_LIVE.md).

### Внутренние статьи и новости

Дизайн центрального блока взят из `article-page.html`; сайдбары остаются общими.
В админке «Статьи» / «Новости» → «Блоки внутри материала» задаются содержание,
цитата, изображение с подписью, ссылка на другой материал, вывод и встроенный прогноз.
Пустые блоки скрыты. «После абзаца» задаёт место вставки; если абзацев меньше,
блок выводится в конце текста. Для содержания перечислите нужные H2/H3 по одному в строке.
Те же поля доступны в `/cabinet/articles/new/` и при редактировании черновика.
Автор статьи необязателен, у новостей автор не выводится. При изменении заголовка
slug обновляется автоматически; явно изменённый вручную slug сохраняется.
Прежние адреса опубликованных материалов перенаправляются на актуальный с кодом 301.
Новые поля: миграции `cabinet.0079_publication_details`, `front.0020_publication_details`.
