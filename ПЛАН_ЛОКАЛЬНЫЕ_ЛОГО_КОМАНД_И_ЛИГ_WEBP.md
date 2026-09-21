# План: локальное хранение логотипов команд, лиг и спортивных сущностей

## Цель

Перестать отдавать логотипы команд и лиг напрямую по ссылкам API. При синхронизации матчей скачивать изображения один раз, сохранять их локально в `media`, конвертировать в WebP и дальше отдавать с нашего домена.

Целевой формат путей:

- команда футбола: `media/football/team/<team_pk>.webp`
- лига баскетбола: `media/basket/league/<league_pk>.webp`
- страна, если понадобится: `media/common/country/<country_pk>.webp`
- спорт, если понадобится: `media/<sport_code>/sport/<sport_pk>.webp`

В БД в итоге должны использоваться локальные пути, а не API URL.

## Текущее состояние

Файлы, которые надо менять:

- `game/models.py`
  - `Country.logo = URLField`
  - `Sport.image = URLField`
  - `League.logo = URLField`
  - `Team.logo = URLField`
  - `Venue.logo = URLField`
  - `Match.home_team_logo` и `Match.away_team_logo` сейчас берут `Team.logo` или fallback из `raw_data`.
- `game/services/match_sync.py`
  - `_sync_country()`
  - `_sync_venue()`
  - `_sync_league()`
  - `_sync_team()`
  - сейчас просто кладут `payload["logo"]` в URLField.
- Шаблоны уже используют `match.league.logo`, `match.home_team_logo`, `match.away_team_logo`, поэтому при сохранении локального URL в поле визуально почти ничего менять не нужно.

## Шаг 1. Определить модель хранения

Рекомендованный вариант без большого переписывания шаблонов:

1. Оставить старые URL-поля как `remote_logo_url` / `remote_image_url`.
2. Добавить локальные поля:
   - `Country.logo = ImageField(upload_to=...)`
   - `Sport.image = ImageField(upload_to=...)`
   - `League.logo = ImageField(upload_to=...)`
   - `Team.logo = ImageField(upload_to=...)`
   - `Venue.logo = ImageField(upload_to=...)`, если стадионы реально используются в UI.
3. На период миграции можно сделать так:
   - переименовать текущий `logo` в `remote_logo_url`;
   - добавить новый `logo` как `ImageField`;
   - для `Sport.image`: переименовать в `remote_image_url`, добавить новый `image`.

Так шаблоны продолжат обращаться к `.logo` и `.image`, но это уже будет локальный файл.

## Шаг 2. Добавить upload path функции

Файл: `game/models.py`.

Нужны функции:

```python
def sport_media_code(sport) -> str:
    return (getattr(sport, "code", "") or "common").strip().lower()

def team_logo_upload_path(instance, filename):
    code = sport_media_code(instance.sport)
    return f"{code}/team/{instance.pk or 'new'}.webp"

def league_logo_upload_path(instance, filename):
    code = sport_media_code(instance.sport)
    return f"{code}/league/{instance.pk or 'new'}.webp"
```

Важный нюанс: до первого сохранения `pk` еще нет. Поэтому скачивание логотипа лучше делать не через прямое присваивание файла до `save()`, а после `update_or_create`, когда `pk` уже известен.

## Шаг 3. Создать сервис загрузки remote image

Новый файл: `game/services/local_logos.py`.

Ответственность сервиса:

1. Принимать модель, поле, remote URL и тип сущности.
2. Проверять, что URL не пустой.
3. Не скачивать повторно, если локальный файл уже есть и remote URL не поменялся.
4. Скачать изображение через `requests` или `urllib`.
5. Проверить content-type и размер.
6. Открыть через Pillow.
7. Привести к RGB/RGBA.
8. Сохранить WebP через `default_storage` в точный путь:
   - `football/team/123.webp`
   - `basket/league/45.webp`
9. Обновить поле модели через `QuerySet.update()`, чтобы не уйти в лишние save-signals.

Настройки в `settings.py`:

```python
LOCAL_LOGO_DOWNLOAD_ENABLED = env_bool("LOCAL_LOGO_DOWNLOAD_ENABLED", True)
LOCAL_LOGO_TIMEOUT = env_int("LOCAL_LOGO_TIMEOUT", 8)
LOCAL_LOGO_MAX_BYTES = env_int("LOCAL_LOGO_MAX_BYTES", 2 * 1024 * 1024)
LOCAL_LOGO_WEBP_QUALITY = env_int("LOCAL_LOGO_WEBP_QUALITY", 82)
```

## Шаг 4. Подключить сервис в match sync

Файл: `game/services/match_sync.py`.

В `_sync_league()`:

1. В `defaults` сохранить `remote_logo_url`.
2. После `update_or_create()` вызвать:

```python
sync_entity_logo(league, field_name="logo", remote_url=remote_logo_url, kind="league")
```

В `_sync_team()`:

```python
sync_entity_logo(team, field_name="logo", remote_url=remote_logo_url, kind="team")
```

Для стран и спорта можно сделать вторым этапом:

```python
sync_entity_logo(country, field_name="logo", remote_url=remote_logo_url, kind="country")
sync_entity_logo(sport, field_name="image", remote_url=remote_image_url, kind="sport")
```

## Шаг 5. Обновить свойства Match

Файл: `game/models.py`.

Сейчас:

```python
return self.home_team.logo if self.home_team_id and self.home_team else self._raw_value(...)
```

После перехода на локальный `ImageField` надо вернуть URL безопасно:

```python
def _image_url(field) -> str:
    try:
        return field.url if field else ""
    except ValueError:
        return ""
```

И:

```python
return _image_url(self.home_team.logo) if self.home_team_id and self.home_team else self._raw_value(...)
```

То же для:

- `home_team_logo`
- `away_team_logo`
- мест, где шаблоны напрямую используют `match.league.logo`, если поле станет `ImageField`.

Лучше добавить model property:

```python
League.logo_url
Team.logo_url
Country.logo_url
Sport.image_url
```

А потом постепенно заменить шаблоны на `.logo_url`.

## Шаг 6. Миграции

Нужны миграции:

1. `RenameField`:
   - `Country.logo` -> `remote_logo_url`
   - `League.logo` -> `remote_logo_url`
   - `Team.logo` -> `remote_logo_url`
   - `Venue.logo` -> `remote_logo_url`
   - `Sport.image` -> `remote_image_url`
2. `AddField`:
   - новый `logo = ImageField(blank=True, upload_to=...)`
   - новый `image = ImageField(blank=True, upload_to=...)`
3. Индексы не нужны для файловых полей.

Важно: миграция не должна скачивать файлы. Скачивание делаем management command, чтобы не подвесить deploy.

## Шаг 7. Команда для массовой загрузки старых логотипов

Новая команда:

`game/management/commands/download_entity_logos.py`

Примеры:

```bash
python manage.py download_entity_logos --dry-run
python manage.py download_entity_logos --model team --limit 500
python manage.py download_entity_logos --model league
python manage.py download_entity_logos --model country
```

Команда должна:

1. Итерироваться по сущностям с `remote_logo_url`.
2. Пропускать сущности, у которых локальный файл уже есть.
3. Скачивать и сохранять WebP.
4. Печатать статистику:
   - scanned
   - downloaded
   - skipped
   - failed

## Шаг 8. Обновить админку

Файл: `game/admin.py`.

Для `LeagueAdmin`, `TeamAdmin`, `CountryAdmin`, `SportAdmin`:

1. Показать локальный preview.
2. Показать readonly `remote_logo_url`.
3. Добавить action:
   - `download_selected_logos`
   - `clear_local_logos`

## Шаг 9. Обновить шаблоны

Минимальный путь:

Если поле `logo` останется `ImageField`, шаблоны вида:

```django
{% if match.league.logo %}
    <img src="{{ match.league.logo }}" ...>
{% endif %}
```

надо заменить на:

```django
{% if match.league.logo %}
    <img src="{{ match.league.logo.url }}" ...>
{% endif %}
```

Но лучше сделать properties `logo_url` и менять на:

```django
{% if match.league.logo_url %}
    <img src="{{ match.league.logo_url }}" ...>
{% endif %}
```

Файлы, которые точно надо проверить:

- `templates/game/includes/_match_card_home.html`
- `templates/game/includes/_match_card.html`
- `templates/game/match_detail.html`
- `templates/game/includes/_match_table_sport.html`
- `templates/cabinet/_coupon_slip.html`
- `templates/front/index.html`
- `templates/front/_prediction_card.html`
- `templates/front/includes/_home_best_prediction_row.html`
- `templates/front/includes/_prediction_table_view.html`

## Шаг 10. Поведение при ошибках

Если загрузка логотипа не удалась:

1. Не ломать sync матча.
2. Оставить `remote_logo_url` в БД.
3. В UI показывать fallback-инициал или SVG.
4. Логировать ошибку через logger:

```python
logger.info("Logo download failed for %s %s: %s", model_name, pk, exc)
```

## Шаг 11. Важные правила

- Не скачивать картинки при каждом рендере страницы.
- Не скачивать картинки в шаблонах.
- Не скачивать картинки внутри миграции.
- Не удалять `remote_logo_url` сразу: он нужен для повторной загрузки и диагностики.
- Не хранить оригиналы PNG/JPG, сразу сохранять WebP.
- Не использовать API URL в финальном UI, если локальный файл уже есть.

## Рекомендуемый порядок внедрения

1. Добавить локальные поля и миграции.
2. Добавить сервис `game/services/local_logos.py`.
3. Подключить сервис к `_sync_team()` и `_sync_league()`.
4. Добавить properties `.logo_url`.
5. Обновить самые видимые шаблоны матчей и главной.
6. Добавить management command для старых данных.
7. Прогнать:

```bash
python manage.py download_entity_logos --model team --dry-run
python manage.py download_entity_logos --model league --dry-run
python manage.py download_entity_logos --model team --limit 100
python manage.py download_entity_logos --model league --limit 100
```

8. После проверки прогнать без limit.

