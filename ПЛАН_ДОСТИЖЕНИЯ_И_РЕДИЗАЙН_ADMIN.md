# План: отдельное приложение достижений и редизайн Django Admin

Цель: сделать достижения управляемыми из админки, с иконками, условиями, выдачей пользователям и уведомлениями. Отдельно привести `/admin/` к визуальному виду как на скрине: темная левая навигация, светлый dashboard, поиск, карточки приложений, быстрые действия, последние действия, адаптив под мобильный.

## 0. Текущая ситуация в проекте

Сейчас достижения не являются полноценными моделями:

- основная логика захардкожена в `cabinet/achievements.py`;
- определения достижений лежат в константах:
  - `EXPERT_ACHIEVEMENT_DEFINITIONS`
  - `REFERRAL_ACHIEVEMENT_DEFINITIONS`
  - `USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS`
- шаблоны профиля читают словари с ключами `key`, `label`, `description`, `icon`, `category`, `progress`;
- иконки сейчас статические: `front/img/badges/*.svg`;
- уведомления о достижениях уже частично есть в `notifications`:
  - `Notification.Kind.ACHIEVEMENT`
  - `NotificationPreference.achievement`
  - `AchievementState`
  - celery beat задача `notification-achievement-sync` в `cappers/settings.py`;
- турнирные достижения отдельные: `tournaments.models.TournamentAchievement`.

Вывод: нужно не “добавить еще один список”, а вынести текущие hardcoded достижения в отдельное приложение и оставить совместимость с текущими шаблонами.

## 1. Создать отдельное Django app `achievements`

Команда:

```bash
python manage.py startapp achievements
```

Добавить app в `cappers/settings.py`:

```python
INSTALLED_APPS = [
    ...
    "achievements.apps.AchievementsConfig",
    ...
]
```

Рекомендуемая структура:

```text
achievements/
  __init__.py
  apps.py
  admin.py
  models.py
  services.py
  evaluators.py
  migrations/
  management/
    commands/
      seed_achievements.py
      sync_achievements.py
  tests/
    test_models.py
    test_services.py
```

## 2. Модели достижений

Файл: `achievements/models.py`

### 2.1. `AchievementCategory`

Нужна для группировки в админке и UI.

Поля:

- `title`: название, например `Прогнозы`, `Победы`, `ROI`, `Аудитория`, `Активность`, `Рефералы`;
- `slug`: уникальный slug;
- `description`: опционально;
- `icon`: опциональная иконка категории;
- `color`: цвет категории, например `#1677ff`;
- `sort_order`: порядок;
- `is_active`;
- `created_at`, `updated_at`.

### 2.2. `Achievement`

Главная модель достижения.

Поля:

- `category = ForeignKey(AchievementCategory)`;
- `key = SlugField(unique=True)`;
- `title`;
- `description`;
- `short_description`;
- `icon = ImageField(upload_to="achievements/icons/")`;
- `fallback_static_icon = CharField(blank=True)`, чтобы временно поддержать старые `front/img/badges/*.svg`;
- `audience`: choices:
  - `all`
  - `reader`
  - `analyst`
- `metric`: choices:
  - `predictions`
  - `wins`
  - `roi`
  - `followers`
  - `streak`
  - `verified`
  - `likes_given`
  - `favorites_saved`
  - `referrals`
  - `custom`
- `target_value = DecimalField(...)`;
- `condition_operator`: choices:
  - `gte`
  - `lte`
  - `eq`
- `is_active`;
- `is_secret`: если true, скрывать до получения;
- `show_progress`: показывать прогресс;
- `coins_reward`: опционально, если позже нужно давать монеты;
- `xp_reward`: опционально;
- `sort_order`;
- `created_at`, `updated_at`.

Индексы:

- `("is_active", "audience", "sort_order")`
- `("metric", "target_value")`

### 2.3. `UserAchievement`

Факт получения достижения пользователем.

Поля:

- `user = ForeignKey(settings.AUTH_USER_MODEL, related_name="achievements")`;
- `achievement = ForeignKey(Achievement, related_name="user_achievements")`;
- `unlocked_at`;
- `progress_value = DecimalField(...)`;
- `progress_percent = PositiveSmallIntegerField(default=100)`;
- `source = CharField`, choices:
  - `auto`
  - `manual`
  - `migration`
  - `admin`
- `metadata = JSONField(default=dict, blank=True)`;

Constraint:

```python
UniqueConstraint(fields=["user", "achievement"], name="unique_user_achievement")
```

Индексы:

- `("user", "-unlocked_at")`
- `("achievement", "-unlocked_at")`

### 2.4. `AchievementProgressSnapshot`

Опционально, но полезно для админки и уведомлений. Хранит последний прогресс даже если достижение еще не получено.

Поля:

- `user`
- `achievement`
- `current_value`
- `progress_percent`
- `updated_at`

Constraint:

- `UniqueConstraint(fields=["user", "achievement"], ...)`

Если хочется проще для первого этапа, эту модель можно пропустить и считать прогресс на лету.

## 3. Миграции и перенос старых достижений

После моделей:

```bash
python manage.py makemigrations achievements
python manage.py migrate
```

Создать management command:

Файл: `achievements/management/commands/seed_achievements.py`

Задача:

- взять текущие константы из `cabinet/achievements.py`;
- создать категории;
- создать `Achievement`;
- заполнить:
  - `key`;
  - `title = label`;
  - `description`;
  - `fallback_static_icon = icon`;
  - `metric`;
  - `target_value`;
  - `category`;
  - `audience`.

Правила audience:

- `EXPERT_ACHIEVEMENT_DEFINITIONS` и `REFERRAL_ACHIEVEMENT_DEFINITIONS` → `analyst`;
- `USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS` → `all`.

Команда должна быть idempotent: повторный запуск обновляет записи, а не создает дубли.

```bash
python manage.py seed_achievements
```

## 4. Сервис расчета достижений

Файл: `achievements/evaluators.py`

Создать функции:

```python
def user_achievement_metrics(user, *, followers_count=None, is_verified=None) -> dict:
    ...
```

Метрики должны соответствовать текущей логике из `cabinet/achievements.py`:

- `predictions`: опубликованные купоны пользователя;
- `wins`: опубликованные выигранные купоны;
- `roi`: текущий ROI;
- `followers`: количество подписчиков;
- `streak`: лучшая серия побед;
- `verified`: 1/0;
- `likes_given`: сколько лайков поставил пользователь;
- `favorites_saved`: сколько сохранил;
- `referrals`: подписавшиеся рефералы.

Важно:

- не делать N+1;
- для списка пользователей использовать отдельную batch-функцию позже;
- для одного профиля можно считать обычными aggregate-запросами.

Файл: `achievements/services.py`

Основные функции:

```python
def active_achievements_for_user(user):
    ...

def build_achievement_overview(user, *, followers_count=0, is_verified=False) -> dict:
    ...

def sync_user_achievements(user, *, notify=True) -> list[UserAchievement]:
    ...

def award_achievement(user, achievement, *, source="auto", progress_value=None, metadata=None):
    ...
```

`build_achievement_overview()` должен возвращать тот же формат, который сейчас ожидают шаблоны:

- `items`;
- `unlocked_count`;
- `total_count`;
- `completion_percent`;
- `next_achievement`;
- `metrics`.

Каждый item должен иметь:

- `key`;
- `label`;
- `title`;
- `description`;
- `icon`;
- `icon_url`;
- `category`;
- `unlocked`;
- `progress`;
- `current_label`;
- `target_label`.

Для обратной совместимости:

- если у `Achievement.icon` есть файл, отдавать `icon_url`;
- если нет, отдавать `fallback_static_icon` в поле `icon`.

## 5. Заменить старый `cabinet/achievements.py`

Файл: `cabinet/achievements.py`

Не удалять сразу, чтобы не ломать импорты. Сделать тонкий compatibility wrapper:

```python
from achievements.services import build_achievement_overview, build_achievement_badges
```

Функции, которые сейчас импортируются:

- `build_achievement_overview`
- `build_achievement_badges`

должны продолжить работать.

Проверить импорты:

- `cabinet/views.py`
- `front/home_views.py`
- `cabinet/expert_profile_views.py`
- возможно другие места через `rg "build_achievement"`.

## 6. Админка достижений

Файл: `achievements/admin.py`

### 6.1. `AchievementCategoryAdmin`

Настройки:

- `list_display = ("title", "slug", "sort_order", "is_active")`
- `list_editable = ("sort_order", "is_active")`
- `search_fields = ("title", "slug")`
- `prepopulated_fields = {"slug": ("title",)}`
- `ordering = ("sort_order", "title")`

### 6.2. `AchievementAdmin`

Настройки:

- `list_display = ("icon_preview", "title", "key", "category", "audience", "metric", "target_value", "is_active", "sort_order")`
- `list_filter = ("is_active", "audience", "metric", "category")`
- `list_editable = ("is_active", "sort_order")`
- `search_fields = ("title", "key", "description")`
- `autocomplete_fields = ("category",)`
- `readonly_fields = ("icon_preview", "created_at", "updated_at")`
- `fieldsets`:
  - Основное: `category`, `key`, `title`, `description`, `short_description`;
  - Иконка: `icon`, `fallback_static_icon`, `icon_preview`, `color`;
  - Условие: `audience`, `metric`, `condition_operator`, `target_value`;
  - Награды: `coins_reward`, `xp_reward`;
  - Показы: `is_active`, `is_secret`, `show_progress`, `sort_order`;
  - Система: `created_at`, `updated_at`.

`icon_preview`:

```python
def icon_preview(self, obj):
    if obj.icon:
        return format_html('<img src="{}" style="width:32px;height:32px;object-fit:contain">', obj.icon.url)
    if obj.fallback_static_icon:
        return obj.fallback_static_icon
    return "—"
```

### 6.3. `UserAchievementAdmin`

Настройки:

- `list_display = ("user", "achievement", "source", "progress_percent", "unlocked_at")`
- `list_filter = ("source", "achievement__category", "achievement")`
- `search_fields = ("user__username", "user__email", "achievement__title", "achievement__key")`
- `autocomplete_fields = ("user", "achievement")`
- `readonly_fields = ("unlocked_at",)`
- action `resync_selected_users`.

### 6.4. Ручная выдача достижения

Через `UserAchievementAdmin` можно добавлять вручную.

Дополнительно можно добавить action в `AchievementAdmin`:

- “Пересчитать это достижение для всех пользователей”;
- это может быть тяжелой операцией, лучше на первом этапе сделать management command, а action показывать только superuser.

## 7. Уведомления о достижениях

Сейчас в `notifications` уже есть `Notification.Kind.ACHIEVEMENT`.

Нужно найти текущую реализацию:

```bash
rg -n "sync_achievement|AchievementState|ACHIEVEMENT" notifications cabinet
```

План:

- перенести определение “какие достижения новые” в `achievements.services.sync_user_achievements`;
- уведомление создавать только для новых `UserAchievement`;
- `notifications.tasks.sync_achievement_notifications` должен вызывать новый сервис;
- `AchievementState` можно оставить временно как защиту от дублей, но лучше постепенно перейти на `UserAchievement` как источник истины.

Event key уведомления:

```python
event_key = f"achievement:{user.pk}:{achievement.key}"
```

## 8. Обновить шаблоны профиля

Основные файлы:

- `templates/cabinet/profile.html`
- `templates/cabinet/_expert_public_achievements.html`
- `templates/front/includes/_home_best_experts.html`
- `front/static/front/js/profile.js`

Текущие шаблоны используют `{% static achievement.icon %}`.

Нужно поддержать оба варианта:

```django
{% if achievement.icon_url %}
  <img src="{{ achievement.icon_url }}" ...>
{% else %}
  <img src="{% static achievement.icon %}" ...>
{% endif %}
```

Так старые SVG из static продолжат работать, а новые загруженные через админку тоже появятся.

## 9. Команды синхронизации

Файл: `achievements/management/commands/sync_achievements.py`

Возможности:

```bash
python manage.py sync_achievements --user-id 123
python manage.py sync_achievements --all
python manage.py sync_achievements --dry-run
```

Для `--all`:

- идти чанками;
- использовать `.iterator(chunk_size=500)`;
- не падать на одном пользователе, логировать ошибки.

## 10. Тесты достижений

Создать:

- `achievements/tests/test_services.py`
- `achievements/tests/test_admin.py`

Проверить:

1. `seed_achievements` создает записи из старых definition.
2. Повторный `seed_achievements` не создает дубли.
3. Пользователь получает achievement при достижении target.
4. Неактивное достижение не показывается и не выдается.
5. `build_achievement_overview` возвращает совместимый формат.
6. Иконка из `ImageField` имеет приоритет над `fallback_static_icon`.
7. Ручная выдача через `UserAchievement` не дублируется.

## 11. Редизайн Django Admin под скрин

Цель: внешний вид `/admin/` как на скрине:

- темный сайдбар слева;
- логотип “Django Admin”;
- список приложений с иконками;
- светлый dashboard;
- верхний поиск;
- приветственный hero;
- карточки приложений;
- блок быстрых действий;
- блок последних действий;
- мобильная адаптация как справа на скрине.

Не ставить стороннюю тему на первом этапе. Лучше сделать кастомные Django admin templates/static. Так проще попасть “в точности как на скрине” и не конфликтовать с текущими `ModelAdmin`.

### 11.1. Создать структуру шаблонов и статики

Добавить:

```text
templates/admin/base_site.html
templates/admin/index.html
templates/admin/app_index.html
templates/admin/includes/app_card.html
templates/admin/includes/sidebar.html
templates/admin/includes/topbar.html
templates/admin/includes/quick_actions.html
templates/admin/includes/recent_actions.html
static/admin_custom/css/admin-dashboard.css
static/admin_custom/js/admin-dashboard.js
```

В проекте static лежит в `front/static/...`, но для admin лучше использовать:

```text
front/static/admin_custom/...
```

Если `STATICFILES_DIRS` настроен иначе, проверить `cappers/settings.py`.

### 11.2. Настроить заголовки admin

Файл: создать `cappers/admin.py` или использовать место, которое импортируется при старте.

```python
from django.contrib import admin

admin.site.site_header = "Django Admin"
admin.site.site_title = "Django Admin"
admin.site.index_title = "Панель управления"
```

Важно: файл должен импортироваться. Если `cappers/admin.py` сам не импортируется, лучше добавить настройки в `cappers/urls.py` рядом с `admin.site.urls`.

### 11.3. Группировка приложений как на скрине

Нужна не стандартная группировка по app label, а человекочитаемые разделы:

- Backend — серверная часть;
- Front — веб-интерфейс;
- Cabinet — пользователи;
- Уведомления — сообщения и алерты;
- Боты — Telegram и другое;
- Игры — игровые модули;
- Кошелёк — платежи и балансы;
- Периодические задачи — запланированные задачи;
- Страницы — контент сайта;
- SEO — метатеги и аналитика;
- Достижения — бейджи и условия.

Создать helper:

Файл: `cappers/admin_dashboard.py`

```python
ADMIN_APP_GROUPS = {
    "back": {"title": "Backend", "subtitle": "Серверная часть", "icon": "database", "color": "blue"},
    "front": {"title": "Front", "subtitle": "Веб-интерфейс", "icon": "monitor", "color": "blue"},
    "cabinet": {"title": "Cabinet", "subtitle": "Пользователи", "icon": "user", "color": "green"},
    "notifications": {"title": "Уведомления", "subtitle": "Сообщения и алерты", "icon": "bell", "color": "red"},
    "bots": {"title": "Боты", "subtitle": "Telegram и другое", "icon": "bot", "color": "purple"},
    "game": {"title": "Игры", "subtitle": "Игровые модули", "icon": "gamepad", "color": "violet"},
    "wallets": {"title": "Кошелёк", "subtitle": "Платежи и балансы", "icon": "wallet", "color": "green"},
    "django_celery_beat": {"title": "Периодические задачи", "subtitle": "Запланированные задачи", "icon": "clock", "color": "orange"},
    "pages": {"title": "Страницы", "subtitle": "Контент сайта", "icon": "file", "color": "yellow"},
    "achievements": {"title": "Достижения", "subtitle": "Бейджи и условия", "icon": "award", "color": "cyan"},
}
```

Также сделать функцию:

```python
def build_admin_dashboard_context(request, app_list):
    ...
```

Она должна вернуть:

- `dashboard_apps`: список карточек с title/subtitle/icon/color/model_count/app_url/models;
- `quick_actions`;
- `recent_actions`.

### 11.4. Передать кастомный context в admin index

Самый чистый вариант: subclass `AdminSite`.

Файл: `cappers/admin_site.py`

```python
from django.contrib.admin import AdminSite

class CappersAdminSite(AdminSite):
    site_header = "Django Admin"
    site_title = "Django Admin"
    index_title = "Панель управления"

    def index(self, request, extra_context=None):
        app_list = self.get_app_list(request)
        extra_context = extra_context or {}
        extra_context.update(build_admin_dashboard_context(request, app_list))
        return super().index(request, extra_context=extra_context)
```

Но переход на кастомный `AdminSite` требует регистрировать все модели заново или аккуратно заменить `admin.site.__class__`, что рискованно.

Более простой первый этап:

- оставить стандартный `admin.site`;
- в `templates/admin/index.html` использовать стандартную переменную `app_list`;
- группировку и карточки делать в template tag.

Создать:

```text
cappers/templatetags/admin_dashboard.py
```

Теги:

- `admin_app_meta app.app_label`
- `admin_grouped_apps app_list`
- `admin_icon_svg icon_name`

### 11.5. Иконки как на скрине

Не подключать внешние SVG CDN. Сделать inline SVG map в template tag или один include:

Иконки:

- home;
- database;
- monitor;
- user;
- bell;
- bot;
- gamepad;
- wallet;
- clock;
- file;
- chart/seo;
- award;
- search;
- sun;
- chevron-right;
- settings.

Файл:

```text
templates/admin/includes/icons.html
```

или tag `admin_icon`.

Цветовые токены:

- blue: `#1478ff`
- green: `#12b981`
- red: `#ff4f66`
- purple: `#5b4bff`
- violet: `#7c4dff`
- orange: `#ff8a1f`
- yellow: `#f5a300`
- cyan: `#0bbf9a`

### 11.6. `templates/admin/base_site.html`

Наследоваться от стандартного:

```django
{% extends "admin/base.html" %}
{% load static %}

{% block extrastyle %}
{{ block.super }}
<link rel="stylesheet" href="{% static 'admin_custom/css/admin-dashboard.css' %}">
{% endblock %}

{% block extrahead %}
{{ block.super }}
<script src="{% static 'admin_custom/js/admin-dashboard.js' %}" defer></script>
{% endblock %}
```

Но для полного совпадения со скрином лучше переопределить `bodyclass`, `branding`, `nav-sidebar`, `content`.

### 11.7. `templates/admin/index.html`

Сверстать:

```text
admin-shell
  admin-sidebar
    brand
    nav apps
    settings bottom
  admin-main
    admin-topbar
      search
      theme button
      user dropdown
    admin-hero
      title "Добро пожаловать!"
      subtitle
      illustration
    admin-app-grid
      app cards
    admin-bottom-grid
      quick actions
      recent actions
```

Использовать стандартные URL из `app.models`:

- у model есть `admin_url`;
- у model есть `add_url`;
- у app есть `app_url`;

Карточка приложения:

- иконка слева;
- title;
- subtitle;
- количество моделей;
- chevron справа.

### 11.8. Поиск в админке

На скрине поиск “по приложениям, моделям, пользователям”.

Первый этап:

- клиентский поиск по карточкам и моделям на главной admin;
- input `[data-admin-search]`;
- JS фильтрует карточки по `data-search`.

Файл: `front/static/admin_custom/js/admin-dashboard.js`

Логика:

- слушать input;
- скрывать app cards, если title/models не совпадают;
- показывать “ничего не найдено”.

Второй этап, если нужен глобальный поиск:

- сделать endpoint `/admin/search/`;
- искать по моделям с `search_fields`;
- это сложнее, лучше не делать в первой версии.

### 11.9. Быстрые действия

В шаблон добавить фиксированные quick actions:

- Добавить пользователя → `admin:cabinet_user_add`;
- Добавить страницу → `admin:front_staticpage_add` или `admin:pages_pageseo_add` в зависимости от нужного;
- Открыть сайт → `/`;
- Документация → `/admin/doc/` если включен admindocs, иначе ссылка пустая/скрытая;
- Добавить достижение → `admin:achievements_achievement_add`.

Важно: перед выводом проверять права:

```django
{% if perms.cabinet.add_user %}
...
{% endif %}
```

### 11.10. Последние действия

Можно использовать стандартный context `admin_log`.

В `templates/admin/index.html`:

- пройти по `admin_log`;
- показать action flag цветом:
  - add → green;
  - change → blue/orange;
  - delete → red.

Если `admin_log` недоступен, использовать стандартный include `admin/includes/object_delete_summary.html` не нужно; лучше скопировать минимальную логику из стандартного `admin/index.html`.

### 11.11. Адаптив как на скрине

CSS breakpoints:

- desktop >= 1024:
  - sidebar fixed/left 280px;
  - content max-width;
  - app grid 3 колонки;
- tablet 768-1023:
  - sidebar 220px;
  - app grid 2 колонки;
- mobile < 768:
  - sidebar превращается в drawer;
  - topbar compact;
  - app cards одной колонкой;
  - кнопка burger.

JS:

- `[data-admin-menu-toggle]` открывает/закрывает sidebar;
- Escape закрывает;
- клик по backdrop закрывает.

### 11.12. CSS требования для совпадения со скрином

Файл: `front/static/admin_custom/css/admin-dashboard.css`

Основные токены:

```css
:root {
  --admin-bg: #eef4fb;
  --admin-panel: rgba(255,255,255,.78);
  --admin-sidebar: #122033;
  --admin-sidebar-2: #0d1a2b;
  --admin-blue: #1478ff;
  --admin-text: #0d1430;
  --admin-muted: #60708f;
  --admin-border: rgba(136, 158, 191, .22);
  --admin-shadow: 0 24px 70px rgba(39, 70, 115, .16);
  --admin-radius: 18px;
}
```

Визуальные правила:

- body background: светлый голубой;
- карточки: белые полупрозрачные, border, shadow;
- sidebar: темно-синий градиент;
- активный пункт меню: ярко-синий pill;
- иконки: цветные квадратные soft backgrounds;
- topbar: glass effect;
- hero: большая типографика, справа 3D-like куб можно сделать CSS/SVG-блоком или статической картинкой.

Для “в точности как на скрине” лучше добавить SVG/PNG иллюстрацию куба в:

```text
front/static/admin_custom/img/admin-hero-cube.svg
```

Не использовать внешние картинки.

### 11.13. Мобильная версия

На мобильном:

- sidebar hidden by default;
- topbar brand + burger + avatar;
- search full width;
- cards compact, как на скрине справа;
- hide quick actions или сделать ниже apps;
- `admin-main` без больших padding.

## 12. Связать новые достижения с новым admin dashboard

После создания app `achievements`:

- добавить meta в `ADMIN_APP_GROUPS`;
- карточка “Достижения” должна показывать количество моделей;
- quick action “Добавить достижение”;
- sidebar пункт “Достижения”.

## 13. Проверки после внедрения

Команды:

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py test achievements
python manage.py test cabinet.tests
python manage.py test notifications.tests
```

Ручная проверка:

- `/admin/` открывается;
- desktop похож на скрин;
- mobile похож на скрин;
- поиск фильтрует карточки;
- все ссылки на модели работают;
- права staff/superuser соблюдаются;
- можно добавить категорию достижения;
- можно добавить достижение с иконкой;
- можно вручную выдать достижение пользователю;
- профиль пользователя показывает новую иконку;
- старые достижения после `seed_achievements` не пропали;
- уведомления о новых достижениях не дублируются.

## 14. Порядок реализации

1. Создать app `achievements`.
2. Добавить модели `AchievementCategory`, `Achievement`, `UserAchievement`.
3. Сделать миграции.
4. Реализовать `seed_achievements`.
5. Реализовать сервисы расчета и выдачи.
6. Сделать `cabinet/achievements.py` compatibility wrapper.
7. Обновить шаблоны под `icon_url` + fallback static.
8. Обновить уведомления на новый сервис.
9. Добавить админку достижений.
10. Добавить тесты достижений.
11. Сделать admin dashboard templates.
12. Сделать admin CSS/JS.
13. Добавить группировку app cards и иконки.
14. Проверить desktop/mobile.
15. Финальный `python manage.py check` и тесты.

## 15. Что нельзя делать

- Не удалять сразу `cabinet/achievements.py`, пока все импорты не переведены.
- Не ломать турнирные достижения `TournamentAchievement`: они отдельные и должны остаться.
- Не заменять стандартный admin сторонней темой без необходимости.
- Не хранить условия достижений только в JSON, если можно выразить их полями `metric/operator/target`.
- Не делать выдачу достижений только при открытии профиля: должна быть команда/задача синхронизации.
- Не делать N+1 при показе достижений в списках капперов.
- Не использовать внешние CDN для иконок админки.
