# План: локальное хранение логотипов команд, лиг и спортивных сущностей

## Цель

Перестать отдавать логотипы команд и лиг напрямую по URL внешнего API.

При синхронизации спортивных данных:

- сохранять исходный URL отдельно для диагностики и повторной загрузки;
- один раз скачивать изображение;
- проверять, что ответ действительно является допустимым изображением;
- конвертировать в WebP;
- сохранять файл в MEDIA_ROOT;
- в UI отдавать URL нашего media storage;
- повторно не скачивать уже сохранённый логотип без явной причины.

Целевые пути:

- футбольная команда: media/football/team/<team_pk>.webp
- баскетбольная лига: media/basket/league/<league_pk>.webp
- страна: media/common/country/<country_pk>.webp
- спорт: media/<sport_media_code>/sport/<sport_pk>.webp
- стадион, если понадобится: media/common/venue/<venue_pk>.webp

Важно: текущий Sport.code для баскетбола в настройках проекта равен basketball. Если нужен именно каталог basket, использовать маленький явный alias только для media path:

~~~python
SPORT_MEDIA_CODE_ALIASES = {
    "basketball": "basket",
}
~~~

Не переименовывать сам Sport.code ради файловой структуры.

---

## 1. Что уже есть в проекте

Перед реализацией учитывать текущий код, чтобы не делать дублирующую архитектуру.

### game/models.py

Сейчас:

- Country.logo — URLField;
- Sport.image — URLField;
- League.logo — URLField;
- Team.logo — URLField;
- Venue.logo — URLField;
- Match.home_team_logo возвращает Team.logo или fallback из raw_data;
- Match.away_team_logo возвращает Team.logo или fallback из raw_data.

### game/services/match_sync.py

Сейчас внешние URL напрямую сохраняются в поля logo:

- _sync_country();
- _sync_venue();
- _sync_league();
- _sync_team().

После update_or_create объект уже имеет pk — это удобная точка для локального сохранения файла.

### cappers/media_webp.py

В проекте уже есть общий WebP-механизм:

- Pillow уже используется;
- есть нормализация RGB/RGBA;
- есть EXIF transpose;
- есть resize;
- используется MEDIA_WEBP_QUALITY;
- есть работа через Django storage;
- есть удаление исходного файла после конвертации.

Новый код логотипов не должен дублировать эту обработку.

### requirements.txt

Pillow уже установлен.

Отдельную библиотеку requests/httpx ради этой задачи не добавлять.

В game/services/providers/neurokeff.py уже используется стандартный urllib, поэтому для скачивания remote image придерживаться того же подхода.

---

## 2. Граница первого этапа

Первый рабочий этап должен полностью покрыть:

1. Team.logo.
2. League.logo.

Country, Sport и Venue подготовить той же моделью данных, но подключать их к загрузке только если они реально нужны в UI.

Причина: команды и лиги используются постоянно, а скачивание всех остальных сущностей сразу увеличит объём изменений без необходимости.

Не делать универсальный media framework для всех моделей проекта.

---

## 3. Изменить модели

Файл:

- game/models.py

### Country

Текущее поле logo переименовать:

~~~python
remote_logo_url = models.URLField(max_length=500, blank=True)
~~~

Добавить:

~~~python
logo = models.ImageField(
    upload_to=country_logo_upload_path,
    blank=True,
)
~~~

### Sport

Текущее поле image переименовать:

~~~python
remote_image_url = models.URLField(max_length=500, blank=True)
~~~

Добавить:

~~~python
image = models.ImageField(
    upload_to=sport_image_upload_path,
    blank=True,
)
~~~

### League

Текущее поле logo переименовать:

~~~python
remote_logo_url = models.URLField(max_length=500, blank=True)
~~~

Добавить:

~~~python
logo = models.ImageField(
    upload_to=league_logo_upload_path,
    blank=True,
)
~~~

### Team

Текущее поле logo переименовать:

~~~python
remote_logo_url = models.URLField(max_length=500, blank=True)
~~~

Добавить:

~~~python
logo = models.ImageField(
    upload_to=team_logo_upload_path,
    blank=True,
)
~~~

### Venue

Если логотип стадиона реально используется в интерфейсе:

~~~python
remote_logo_url = models.URLField(max_length=500, blank=True)

logo = models.ImageField(
    upload_to=venue_logo_upload_path,
    blank=True,
)
~~~

Если Venue.logo нигде не выводится, не подключать скачивание на первом этапе. Поле можно только безопасно переименовать в remote_logo_url и вернуться к локальному ImageField позже.

---

## 4. Добавить функции media path

Файл:

- game/models.py

Сделать маленькие функции, без отдельного слоя ради построения пути.

~~~python
SPORT_MEDIA_CODE_ALIASES = {
    "basketball": "basket",
}


def sport_media_code(sport) -> str:
    code = (getattr(sport, "code", "") or "common").strip().lower()
    return SPORT_MEDIA_CODE_ALIASES.get(code, code)


def team_logo_upload_path(instance, filename):
    return f"{sport_media_code(instance.sport)}/team/{instance.pk or 'new'}.webp"


def league_logo_upload_path(instance, filename):
    return f"{sport_media_code(instance.sport)}/league/{instance.pk or 'new'}.webp"


def country_logo_upload_path(instance, filename):
    return f"common/country/{instance.pk or 'new'}.webp"


def sport_image_upload_path(instance, filename):
    return f"{sport_media_code(instance)}/sport/{instance.pk or 'new'}.webp"


def venue_logo_upload_path(instance, filename):
    return f"common/venue/{instance.pk or 'new'}.webp"
~~~

Критично:

- файл не сохранять до появления pk;
- загрузку remote image вызывать после update_or_create;
- итоговое имя должно быть детерминированным, чтобы один объект не создавал logo_1.webp, logo_2.webp и т.д.

---

## 5. Переиспользовать существующий WebP-конвертер

Файлы:

- cappers/media_webp.py
- game/services/local_logos.py

Не копировать в local_logos.py существующую логику:

- Image.open;
- ImageOps.exif_transpose;
- RGB/RGBA conversion;
- resize;
- quality;
- сохранение WebP.

В cappers/media_webp.py аккуратно выделить из существующего convert_field_file_to_webp небольшой публичный helper для преобразования входного изображения в WebP bytes/ContentFile.

Например:

~~~python
def convert_image_content_to_webp(source) -> ContentFile:
    ...
~~~

После этого:

- существующий convert_field_file_to_webp использует этот helper;
- local_logos.py использует тот же helper для скачанных bytes.

Это оправданное изменение, потому что одна и та же логика будет использоваться минимум в двух местах и реально убирает дублирование.

Не делать новый отдельный image-processing модуль.

---

## 6. Создать сервис загрузки локальных логотипов

Новый файл:

- game/services/local_logos.py

Ответственность файла должна быть узкой:

1. скачать remote URL;
2. проверить базовые ограничения;
3. конвертировать через существующий WebP helper;
4. сохранить в deterministic media path;
5. записать локальный путь в ImageField;
6. не ломать match sync при ошибке.

Основная функция:

~~~python
def sync_entity_logo(
    instance,
    *,
    field_name: str,
    remote_url: str,
    target_name: str,
    force: bool = False,
) -> bool:
    ...
~~~

Не делать registry классов, adapters, strategies или универсальный downloader framework.

---

## 7. Скачивание remote image

Использовать urllib, как уже делает Neurokeff provider.

Настройки:

- cappers/settings.py
- .env.example

Добавить только то, что действительно относится к remote download:

~~~python
LOCAL_LOGO_DOWNLOAD_ENABLED = env_bool("LOCAL_LOGO_DOWNLOAD_ENABLED", True)
LOCAL_LOGO_TIMEOUT = env_int("LOCAL_LOGO_TIMEOUT", 8)
LOCAL_LOGO_MAX_BYTES = env_int("LOCAL_LOGO_MAX_BYTES", 2 * 1024 * 1024)
~~~

Отдельный LOCAL_LOGO_WEBP_QUALITY не добавлять.

Использовать уже существующий:

- MEDIA_WEBP_QUALITY.

Проверки downloader:

- URL начинается с http:// или https://;
- timeout ограничен;
- Content-Length не превышает LOCAL_LOGO_MAX_BYTES, если header есть;
- фактически прочитанные bytes также ограничены LOCAL_LOGO_MAX_BYTES;
- пустой ответ отклоняется;
- Pillow должен реально открыть содержимое;
- неподдерживаемый/битый файл не сохраняется.

Content-Type использовать как дополнительную проверку, но не как единственный источник истины: некоторые CDN возвращают generic content type.

---

## 8. Безопасность remote URL

Так как URL приходит от внешнего sports provider, не превращать downloader в произвольный публичный fetch endpoint.

Правила:

- функция вызывается только серверным sync кодом;
- пользователь не передаёт URL;
- никаких view/API для "скачать картинку по URL";
- не следовать бесконечным redirect;
- ограничить timeout и размер ответа;
- ошибки сети не пробрасывать наружу из match sync.

Если позже источник URL станет пользовательским вводом, отдельно добавить SSRF-защиту. В рамках текущей задачи не строить лишнюю систему заранее.

---

## 9. Сохранять файл напрямую как WebP

Не сохранять сначала PNG/JPG в media, а потом второй раз WebP.

Поток:

1. urllib получает bytes;
2. общий WebP helper конвертирует их в памяти;
3. default_storage сохраняет уже готовый .webp;
4. ImageField получает относительное имя файла.

Пример target name:

~~~python
football/team/123.webp
~~~

или:

~~~python
basket/league/45.webp
~~~

Если target уже существует и force=False:

- повторно не скачивать;
- вернуть skipped/False.

При force=True:

- удалить/перезаписать target;
- сохранить свежий файл.

---

## 10. Не зависеть от post_save WebP signal для remote логотипов

Даже несмотря на наличие cappers/media_webp_signals.py, remote logo pipeline должен явно сохранять уже готовый WebP.

Причины:

- нужен точный deterministic path;
- нельзя сначала сохранить PNG под именем .webp;
- не нужно запускать лишний save/post_save цикл;
- local_logos.py должен быть предсказуемым и тестируемым сам по себе.

Существующий глобальный WebP-механизм остаётся для обычных ImageField upload в проекте.

---

## 11. Обновить match sync

Файл:

- game/services/match_sync.py

### _sync_team()

До update_or_create:

~~~python
remote_logo_url = str(payload.get("logo") or "")
~~~

В defaults:

~~~python
"remote_logo_url": remote_logo_url,
~~~

После update_or_create:

~~~python
sync_entity_logo(
    team,
    field_name="logo",
    remote_url=remote_logo_url,
    target_name=team_logo_upload_path(team, ""),
)
~~~

### _sync_league()

То же самое:

~~~python
sync_entity_logo(
    league,
    field_name="logo",
    remote_url=remote_logo_url,
    target_name=league_logo_upload_path(league, ""),
)
~~~

### _sync_country()

На первом этапе достаточно:

- сохранять remote_logo_url;
- локальную загрузку включить только если страна реально отображается с флагом/лого.

### _sync_venue()

На первом этапе:

- сохранять remote_logo_url;
- не скачивать файл, если Venue.logo не используется в UI.

### Sport

Сейчас Sport создаётся/обновляется отдельно и image практически не участвует в _sync_sport.

Если provider реально присылает sport image:

- сохранить remote_image_url;
- затем вызвать sync_entity_logo(... field_name="image" ...).

Если provider не присылает sport image, не добавлять искусственную загрузку.

---

## 12. Важное правило: ошибка логотипа не ломает sync матча

Синхронизация спортивных данных важнее картинки.

sync_entity_logo должен ловить ожидаемые ошибки:

- HTTPError;
- URLError;
- socket.timeout / TimeoutError;
- OSError;
- Pillow UnidentifiedImageError;
- ValueError.

Логировать компактно:

~~~python
logger.warning(
    "Logo download failed model=%s pk=%s url=%s error=%s",
    instance._meta.label_lower,
    instance.pk,
    remote_url,
    exc,
)
~~~

После ошибки:

- объект Team/League остаётся сохранённым;
- remote_logo_url остаётся в БД;
- logo остаётся пустым или старым;
- match sync продолжается.

Не оборачивать remote download в transaction.atomic вместе с сохранением матча.

Сетевой запрос не должен удерживать транзакцию БД.

---

## 13. Поведение при повторной синхронизации

Основной сценарий:

- локальный target file уже существует;
- logo уже указывает на этот файл;
- force=False;
- downloader ничего не делает.

На первом этапе не добавлять отдельный hash/fingerprint/source-version field только ради автоматического определения изменения картинки.

Для принудительного обновления предусмотреть force=True в сервисе и management command.

Это проще и соответствует цели "скачать один раз".

Если позже окажется, что provider часто меняет картинки по тому же URL, тогда отдельно добавить контроль ETag/hash/updated source URL.

---

## 14. Добавить безопасные URL properties

Файл:

- game/models.py

Чтобы шаблоны не работали напрямую с FieldFile, добавить маленький общий helper:

~~~python
def image_field_url(field) -> str:
    if not field:
        return ""
    try:
        return field.url
    except ValueError:
        return ""
~~~

Для Team:

~~~python
@property
def logo_url(self) -> str:
    return image_field_url(self.logo)
~~~

Для League:

~~~python
@property
def logo_url(self) -> str:
    return image_field_url(self.logo)
~~~

Для Country:

~~~python
@property
def logo_url(self) -> str:
    return image_field_url(self.logo)
~~~

Для Sport:

~~~python
@property
def image_url(self) -> str:
    return image_field_url(self.image)
~~~

Для Venue — только если локальное поле реально используется.

Не добавлять отдельный mixin ради 3–4 однотипных properties.

---

## 15. Обновить Match.home_team_logo и Match.away_team_logo

Файл:

- game/models.py

После перехода Team.logo на ImageField свойства должны возвращать URL строкой, а не FieldFile.

Целевое поведение:

~~~python
@property
def home_team_logo(self) -> str:
    if self.home_team_id and self.home_team:
        return self.home_team.logo_url
    return ""


@property
def away_team_logo(self) -> str:
    if self.away_team_id and self.away_team:
        return self.away_team.logo_url
    return ""
~~~

После завершения миграции UI не должен fallback-ить на raw_data teams.*.logo, потому что это снова внешний API URL.

Если локального файла нет:

- вернуть пустую строку;
- UI показывает существующий fallback/initial/icon.

Remote URL хранится только как источник для повторной загрузки, а не как frontend fallback.

Это важно для выполнения цели: не отдавать API logo URL браузеру.

---

## 16. Обновить шаблоны

Нужно найти все реальные использования через:

~~~bash
rg "\.logo|home_team_logo|away_team_logo|\.image" templates front game cabinet
~~~

Не менять шаблоны списком вслепую.

Правило:

- Team/League/Country использовать через подготовленный *_url property;
- Match использовать через home_team_logo / away_team_logo;
- не использовать remote_logo_url в templates.

Пример:

~~~django
{% if match.league.logo_url %}
    <img
        src="{{ match.league.logo_url }}"
        alt="{{ match.league_name }}"
        width="32"
        height="32"
        loading="lazy"
    >
{% endif %}
~~~

Соблюдать существующее правило проекта:

- у img должны быть width и height.

Skeleton для маленьких логотипов не добавлять.

---

## 17. Миграции

Создать обычную schema migration.

Порядок:

1. RenameField:
   - Country.logo -> Country.remote_logo_url;
   - Sport.image -> Sport.remote_image_url;
   - League.logo -> League.remote_logo_url;
   - Team.logo -> Team.remote_logo_url;
   - Venue.logo -> Venue.remote_logo_url, если поле переносится сейчас.

2. AddField:
   - новые ImageField logo/image.

Плюс:

- никаких сетевых запросов внутри migration;
- никаких download в RunPython;
- существующие URL должны сохраниться после RenameField;
- файлы загружаются отдельной management command.

После миграции:

~~~bash
python manage.py makemigrations --check
~~~

должен быть чистым.

---

## 18. Management command для существующих данных

Новый файл:

- game/management/commands/download_entity_logos.py

Поддержать:

~~~bash
python manage.py download_entity_logos --model team --dry-run
python manage.py download_entity_logos --model league --dry-run
python manage.py download_entity_logos --model team --limit 100
python manage.py download_entity_logos --model league --limit 100
python manage.py download_entity_logos --model team --force
python manage.py download_entity_logos --all
~~~

Минимальные model choices первого этапа:

- team;
- league.

Позже, если подключены:

- country;
- sport;
- venue.

Команда должна:

- использовать iterator(), а не загружать весь queryset в память;
- выбирать только записи с непустым remote URL;
- пропускать уже существующие файлы без force;
- вызывать тот же sync_entity_logo;
- печатать итог:
  - scanned;
  - downloaded;
  - skipped;
  - failed.

Не дублировать download logic внутри команды.

---

## 19. Админка

Файл:

- game/admin.py

На первом этапе достаточно сделать поля видимыми и диагностируемыми.

Для TeamAdmin / LeagueAdmin:

- показать logo preview;
- remote_logo_url сделать readonly;
- logo оставить видимым;
- при необходимости добавить action "Обновить локальные логотипы".

Не добавлять сразу clear action, если реального сценария нет.

Если action добавляется:

- он должен вызывать существующий sync_entity_logo(... force=True);
- не копировать downloader code в admin.py.

Country/Sport/Venue admin обновлять только когда соответствующие локальные поля реально включены.

---

## 20. Тесты

Добавить отдельные небольшие тесты сервиса и интеграции sync.

Предпочтительно:

- game/tests/test_local_logos.py
- существующие match sync tests расширить минимально.

Проверить:

1. valid PNG/JPEG remote bytes сохраняются как настоящий WebP;
2. итоговый путь Team:
   - football/team/<pk>.webp;
3. итоговый путь League для basketball:
   - basket/league/<pk>.webp;
4. существующий файл не скачивается второй раз без force;
5. force=True обновляет файл;
6. слишком большой ответ отклоняется;
7. битое изображение не сохраняется;
8. HTTP/network error не выбрасывается из match sync;
9. Team.remote_logo_url сохраняется;
10. League.remote_logo_url сохраняется;
11. home_team_logo возвращает локальный MEDIA_URL;
12. away_team_logo возвращает локальный MEDIA_URL;
13. при отсутствии local logo свойства не возвращают внешний raw_data URL;
14. management command dry-run не пишет файлы.

Для network использовать mock urlopen, без реальных HTTP-запросов.

Для storage использовать временный MEDIA_ROOT через override_settings.

---

## 21. Настройки deploy/media

Проверить текущую production схему media.

Сейчас проект использует:

- MEDIA_ROOT;
- FileSystemStorage;
- MEDIA_URL.

Для локальной разработки этого достаточно.

На production нужно убедиться, что каталог media:

- persistent между deploy;
- примонтирован как volume;
- отдаётся nginx;
- не хранится только внутри эфемерного app container.

Не коммитить сгенерированные team/league WebP в Git.

---

## 22. Производительность

Не делать download на каждый Match отдельно, если одна Team/League повторяется в сотнях матчей.

Защита от повторов обеспечивается deterministic target file:

- если football/team/123.webp существует — skip;
- если football/league/45.webp существует — skip.

Дополнительно в рамках одного MatchSyncService можно при необходимости держать простой set успешно проверенных entity keys, но добавлять его только если профилирование покажет лишние storage.exists вызовы.

Не добавлять Redis cache только для этого.

---

## 23. Что не делать

- Не хранить внешний API URL в новом logo/image поле.
- Не отдавать remote_logo_url в templates.
- Не оставлять fallback на raw_data logo после завершения перехода.
- Не скачивать изображения во view.
- Не скачивать изображения в template.
- Не скачивать изображения в model.save().
- Не делать сетевые запросы в migration.
- Не держать network request внутри transaction.atomic.
- Не добавлять requests/httpx только ради logo downloader.
- Не создавать отдельную очередь/Celery pipeline на первом этапе.
- Не создавать новый image framework.
- Не дублировать Pillow-конвертацию из cappers/media_webp.py.
- Не добавлять skeleton для маленьких team/league logo.
- Не менять остальные части match sync без необходимости.

---

## 24. Порядок реализации

1. Через rg найти все использования текущих logo/image полей.
2. Добавить upload path функции.
3. Переименовать URL-поля в remote_*.
4. Добавить ImageField.
5. Сделать migration.
6. Выделить переиспользуемый raw-image -> WebP helper из cappers/media_webp.py.
7. Добавить game/services/local_logos.py.
8. Подключить Team и League в match_sync.py.
9. Добавить logo_url/image_url properties.
10. Убрать raw_data API-logo fallback из Match.
11. Обновить реальные template usages.
12. Добавить download_entity_logos management command.
13. Добавить тесты.
14. Прогнать dry-run.
15. Скачать первые 50–100 Team/League и проверить файлы/URL.
16. После проверки выполнить полный backfill.

---

## 25. Команды проверки

Минимально:

~~~bash
python manage.py check
python manage.py makemigrations --check
python manage.py test game
~~~

Если весь game test suite долгий:

~~~bash
python manage.py test game.tests.test_local_logos
~~~

Backfill сначала только dry-run:

~~~bash
python manage.py download_entity_logos --model team --dry-run
python manage.py download_entity_logos --model league --dry-run
~~~

Потом маленькая выборка:

~~~bash
python manage.py download_entity_logos --model team --limit 100
python manage.py download_entity_logos --model league --limit 100
~~~

После этого вручную проверить:

- несколько футбольных матчей;
- баскетбольный матч;
- список матчей;
- detail матча;
- карточку прогноза;
- страницу, где показывается logo league;
- Network в браузере: src логотипов должен быть /media/...webp, а не домен sports API.

---

## 26. Критерий готовности

Задача считается завершённой, когда:

- новый Team/League из API получает remote_logo_url;
- logo сохраняется локально в WebP;
- файл имеет deterministic путь;
- повторный sync не скачивает существующий logo снова;
- UI использует только local media URL;
- при падении image CDN match sync продолжает работать;
- старые Team/League можно backfill одной management command;
- внешний logo URL остаётся только в remote_logo_url для диагностики/force refresh;
- python manage.py check проходит;
- тесты local logo pipeline проходят.
