# План доработок бонусов, профиля, промо-баннеров и уведомлений

Цель: привести бонусные страницы, профиль, уровни, промо-баннеры и уведомления к понятной системе без лишней архитектуры. Делать по `Agent.md`: минимальные изменения, стили только в `main.css/mobile.css`, без inline style, без новых CSS-файлов, без skeleton для маленьких AJAX.

## Шаг 1. Исправить прогресс уровней

Проблема: пользователь на уровне “Новичок”, но визуально заполняются другие уровни.

Файлы:

- `cabinet/services/xp.py`
- `cabinet/services/bonus_center.py`
- `templates/cabinet/bonus_levels.html`
- `front/static/front/css/main.css`

Что сделать:

- В списке уровней заполнять progress так:
  - уровни ниже текущего: `100%`;
  - текущий уровень: реальный progress до следующего уровня;
  - уровни выше текущего: `0%`.
- Не использовать общий `level_progress.progress_percent` для всех rows.
- Для каждого level item подготовить:
  - `progress_percent`;
  - `progress_class`: `is-progress-0`, `is-progress-10` ... `is-progress-100`;
  - `status_label`: `Текущий`, `Открыт`, `Впереди`;
  - `is_current`, `is_unlocked`, `is_locked`.
- В шаблоне не считать проценты.

## Шаг 2. Расширить модель уровней XP

Файл:

- `cabinet/models.py`

Модель:

- `XpLevel`

Добавить необязательные поля:

- `icon = models.ImageField("Иконка", upload_to="xp_levels/icons/%Y/%m/", blank=True)`
- `image = models.ImageField("Изображение", upload_to="xp_levels/images/%Y/%m/", blank=True)`
- `description = RichTextField("Описание", blank=True)` если CKEditor/RichText уже есть в проекте.
- Если RichTextField в проекте нет, использовать `models.TextField("Описание", blank=True)` и явно написать TODO на подключение rich text позже.

Важно:

- не подключать новую richtext-библиотеку ради одного поля, если в проекте её нет;
- сделать миграцию;
- добавить поля в админку.

## Шаг 3. Обновить админку уровней

Файл:

- `cabinet/admin.py`

Для `XpLevelAdmin` добавить:

- `icon`;
- `image`;
- `description`;
- preview readonly, если в админке уже есть паттерн preview image.

Не писать сложный кастомный виджет.

## Шаг 4. Красиво показать текущий уровень в `profile-hero`

Страница:

- `/cabinet/profile/?tab=profile`

Файлы:

- `cabinet/views.py`
- `cabinet/services/bonus_center.py`
- `templates/cabinet/profile.html`
- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Что сделать:

- В `build_profile_bonus_summary(user)` добавить hero payload:
  - `current_level_title`;
  - `current_level_number`;
  - `xp`;
  - `target_label`;
  - `status_label`;
  - `progress_class`;
  - `icon_url`;
  - `image_url`.
- В `profile-hero` добавить compact XP-блок.
- Использовать визуальный стиль `bonus-side-card bonus-progress-card`, но адаптировать под hero:
  - маленькое кольцо прогресса;
  - текущий уровень;
  - “85 XP до следующего уровня”.
- Не переносить весь sidebar block как есть, а вынести аккуратный mini-view, чтобы hero не стал перегруженным.

## Шаг 5. Дать VIP-капперам менять обложку `profile-hero`

Файлы:

- `cabinet/models.py`
- `cabinet/forms.py` или отдельная form рядом с профилем
- `cabinet/avatar_views.py` или новый endpoint в существующем profile/avatar module
- `cabinet/urls.py`
- `templates/cabinet/profile.html`
- `front/static/front/js/profile.js`
- `front/static/front/css/main.css`

Что сделать:

- Добавить поле для обложки профиля, лучше в `AnalystProfile`:
  - `cover_image = models.ImageField("Обложка профиля", upload_to="profile_covers/%Y/%m/", blank=True)`
- Доступ:
  - только `request.user.is_analyst`;
  - только активный VIP: использовать canonical `user.is_vip`;
  - обычному капперу не показывать загрузку.
- Endpoint:
  - `POST /cabinet/profile/cover/`
  - AJAX upload как avatar;
  - проверка типа/размера изображения;
  - удалить старый файл после успешной замены, как сделано для avatar.
- Template:
  - в `profile-hero` использовать cover image, если есть;
  - кнопка “Сменить обложку” только VIP-капперу.
- JS:
  - jQuery/AJAX или существующий стиль проекта;
  - без skeleton;
  - disable кнопки во время upload;
  - после успеха заменить background/image.

## Шаг 6. Промо-баннеры: отдельные CSS-классы под размеры

Проблема: promo banners нельзя везде стилизовать одним классом, потому что высота будет разная.

Файлы:

- `pages/models.py`
- `pages/admin.py`
- `pages/promo_banners.py`
- templates, где рендерятся promo banners
- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Что добавить:

- поле `size_class` или `variant`:
  - `sidebar_small`;
  - `sidebar_medium`;
  - `sidebar_tall`;
  - `center_wide`;
  - `center_compact`;
  - `feed_inline`.
- В template формировать класс:
  - `promo-banner promo-banner--{{ banner.variant }}`;
- Для каждого variant задать стабильную высоту/aspect-ratio в CSS.

Не использовать inline `height`.

## Шаг 7. Промо-баннеры: условия показа

Файлы:

- `pages/models.py`
- `pages/admin.py`
- `pages/promo_banners.py`
- миграция

Добавить audience conditions:

- `all` — всем;
- `anonymous` — гостям;
- `authenticated` — авторизованным;
- `reader` — обычным пользователям;
- `capper` — капперам;
- `vip_capper` — VIP-капперам;
- `non_vip_capper` — капперам без VIP.

В `pages/promo_banners.py` сделать helper:

```python
def promo_banner_matches_user(banner, user) -> bool:
    ...
```

Правила:

- VIP проверять через `user.is_vip`, не через `AnalystProfile.is_vip`;
- фильтровать в service/context processor, не в template;
- не делать сложный rule engine.

## Шаг 8. Улучшить `/cabinet/bonuses/tasks/`

Файлы:

- `templates/cabinet/bonus_tasks.html`
- `cabinet/services/bonus_center.py`
- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Цель: минималистично и читабельно.

Что сделать:

- Убрать визуальный шум.
- Сделать одну понятную колонку заданий:
  - название;
  - краткое описание;
  - прогресс `2 / 3`;
  - награда;
  - статус/кнопка.
- Выполненные задания:
  - перечёркнутый title;
  - muted text;
  - check icon.
- Невыполненные:
  - другой цвет статуса;
  - progress bar.
- Claim button показывать только когда `can_claim=True`.
- Вверху оставить summary: `Сегодня выполнено N из M`.

## Шаг 9. Уведомления о выполнении заданий

Файлы:

- `cabinet/services/daily_tasks.py`
- `cabinet/services/bonus_rewards.py`
- `notifications/models.py`
- `notifications/services.py`
- `notifications/templates/notifications/center.html`

Правило:

- Когда задание стало completed, пользователь получает уведомление “Задание выполнено”.
- Когда он забрал награду, пользователь получает уведомление “Награда получена”, если это ещё не делается через `BonusEvent`.

Лучше:

- completed notification: в `record_daily_task_action` при переходе `is_completed False -> True`;
- reward notification: через `grant_bonus_reward`.

Обязательно:

- не слать повторно;
- event_key стабильный:
  - `daily-task-completed:{user_id}:{task_id}:{date}`;
  - `bonus:{bonus_event_id}`.

## Шаг 10. Профиль: заменить “Быстрые задания” на “Ежедневные задания”

Страница:

- `/cabinet/profile/?tab=profile`

Файлы:

- `cabinet/services/bonus_center.py`
- `templates/cabinet/profile.html`
- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Что сделать:

- Заголовок: `Ежедневные задания`.
- Показывать все задания на сегодня, а не первые 3.
- Выполненные:
  - перечеркнуть;
  - muted;
  - check icon.
- Невыполненные:
  - normal/accent color;
  - показать `current / target`.
- Если задание можно claim:
  - маленькая кнопка “Получить”.
- Внизу ссылка `Все задания`.

Не использовать skeleton.

## Шаг 11. Минималистично переделать `/cabinet/referrals/`

Файлы:

- `templates/cabinet/referrals.html`
- `cabinet/services/referral_bonuses.py`
- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Что сделать:

- Верх:
  - реферальная ссылка;
  - кнопка копирования;
  - короткое объяснение.
- Метрики в одну строку/сетку:
  - переходы;
  - регистрации;
  - подписки;
  - бонусы;
  - заработано, если каппер.
- Ниже:
  - “Как начисляются бонусы” 3 компактных пункта;
  - “Последние рефералы” simple list;
  - “Последние бонусы” simple list.
- Убрать тяжёлые большие cards, если они перегружают страницу.

## Шаг 12. Проверить уведомления рефералов и бонусов

Файлы:

- `cabinet/services/referral_bonuses.py`
- `cabinet/referrals.py`
- `cabinet/services/bonus_rewards.py`
- `notifications/tests.py`
- `cabinet/tests/test_bonus_center.py`

Проверить:

- регистрация по referral link создаёт bonus event и notification;
- первое пополнение создаёт bonus event и notification;
- первая подписка создаёт bonus event и notification;
- отключенный `bonus_referral` не создаёт notification;
- отключенный `bonus_daily_task` не создаёт notification.

## Шаг 13. Админская массовая рассылка уведомлений

Цель: админ может отправить уведомление выбранной аудитории.

Файлы:

- `notifications/models.py`
- `notifications/admin.py`
- `notifications/services.py`
- возможно `notifications/forms.py`
- миграции

Добавить модель:

```python
class AdminNotificationCampaign(models.Model):
    audience = models.CharField(...)
    title = models.CharField(max_length=180)
    message = models.TextField()
    url = models.CharField(max_length=500, blank=True)
    image = models.ImageField(upload_to="notifications/campaigns/%Y/%m/", blank=True)
    inactive_days = models.PositiveIntegerField(null=True, blank=True)
    tournament = models.ForeignKey("tournaments.Tournament", null=True, blank=True, ...)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, ...)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipients_count = models.PositiveIntegerField(default=0)
```

Audience choices:

- `all_users`;
- `vip_users`;
- `readers`;
- `cappers`;
- `readers_and_cappers`;
- `tournament_winners`;
- `tournament_participants`;
- `inactive_users`.

## Шаг 14. Service выбора получателей рассылки

Файл:

- `notifications/services.py` или `notifications/campaigns.py`

Добавить:

```python
def campaign_recipients_queryset(campaign):
    ...
```

Условия:

- `all_users`: все active users;
- `vip_users`: users with active `UserVipSubscription`;
- `readers`: role reader;
- `cappers`: role analyst;
- `readers_and_cappers`: both reader and analyst;
- `tournament_winners`: пользователи, которые выигрывали турниры;
- `tournament_participants`: участники выбранного турнира;
- `inactive_users`: `last_login < now - inactive_days`.

Если точные модели турниров называются иначе, агент обязан сначала открыть `tournaments/models.py` или `rg "class Tournament"`.

## Шаг 15. Admin action отправки campaign

Файл:

- `notifications/admin.py`

Что сделать:

- Зарегистрировать `AdminNotificationCampaign`.
- Добавить action/button “Отправить”.
- При отправке:
  - взять recipients queryset;
  - создать `Notification` каждому через `bulk_create`;
  - `kind = Notification.Kind.ADMIN_CAMPAIGN` добавить в `Notification.Kind`;
  - event_key: `admin-campaign:{campaign_id}:{user_id}`;
  - заполнить `sent_at`, `recipients_count`.
- Не отправлять повторно, если `sent_at` уже заполнен.

## Шаг 16. Изображение в уведомлении

Файлы:

- `notifications/models.py`
- `notifications/templates/notifications/center.html`
- `notifications/static/notifications/js/realtime.js`

Сейчас `Notification` имеет `meta`.

Вариант проще:

- не добавлять image field в `Notification`;
- хранить image url в `notification.meta["image_url"]`.

В template:

- если `notification.meta.image_url`, показать маленькую картинку.

В realtime toast:

- если payload содержит image_url, показать thumbnail.

## Шаг 17. Tests/checklist

Тесты:

- уровень новичка не заполняет будущие уровни;
- XpLevel icon/image/description доступны в admin/context;
- promo banner audience фильтруется для reader/capper/vip capper;
- VIP capper может загрузить cover, non-VIP capper не может;
- daily task completed notification создаётся один раз;
- referral notifications respect preferences;
- admin campaign не отправляется повторно;
- inactive_users audience выбирает пользователей по `last_login`.

Ручная проверка:

- `/cabinet/bonuses/levels/`;
- `/cabinet/bonuses/tasks/`;
- `/cabinet/profile/?tab=profile`;
- `/cabinet/referrals/`;
- `/notifications/`;
- admin campaign create/send.

## Что не делать

- Не добавлять отдельный CSS-файл.
- Не делать универсальный rule engine для баннеров.
- Не использовать skeleton для upload, claim, copy, campaign send.
- Не хранить progress levels в template.
- Не показывать VIP cover upload обычным пользователям.
- Не делать массовую рассылку GET-запросом.
