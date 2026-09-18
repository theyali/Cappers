# План отдельных страниц бонусной системы

Цель: после внедрения бонусного центра добавить нормальные отдельные страницы для ежедневных заданий, уровней и рефералов, а также привести меню кабинета к понятной структуре.

Писать по `Agent.md`: без лишней архитектуры, без inline styles, стили только в `front/static/front/css/main.css` и `front/static/front/css/mobile.css`, данные готовить во view/service, не делать бизнес-логику в templates.

## Решение по страницам

Нужны отдельные страницы:

- `/cabinet/bonuses/` — общий бонусный центр, как dashboard.
- `/cabinet/bonuses/tasks/` — ежедневные задания.
- `/cabinet/bonuses/levels/` — уровни и XP.
- `/cabinet/referrals/` — рефералы как полноценная страница, а не JS-вкладка в профиле.

Отдельная страница серии дней пока НЕ нужна.

Почему:

- серия дней короткая по смыслу: текущая серия, лучшая серия, 7 дней, ближайшая награда;
- отдельная страница будет пустой и усложнит меню;
- серию дней показывать блоком на `/cabinet/bonuses/`, `/cabinet/bonuses/tasks/` и `/cabinet/bonuses/levels/`.

Если позже появится календарь серий, история streak rewards и сезонные серии, тогда добавить `/cabinet/bonuses/streak/`.

## Текущие файлы, на которые опираться

Уже есть:

- `cabinet/bonus_views.py`
- `cabinet/urls.py`
- `cabinet/services/bonus_center.py`
- `cabinet/services/daily_tasks.py`
- `cabinet/services/streaks.py`
- `cabinet/services/xp.py`
- `cabinet/services/referral_bonuses.py`
- `cabinet/referral_views.py`
- `templates/cabinet/bonuses.html`
- `templates/cabinet/includes/_bonus_dashboard_card.html`
- `templates/cabinet/includes/_profile_tab_links.html`
- `templates/cabinet/includes/_profile_tabs_sidebar.html`
- `front/static/front/js/roulette.js`
- `front/static/front/js/profile-referrals.js`
- `front/static/front/js/profile-menu.js`
- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Не создавать новые CSS-файлы.

## Шаг 1. Добавить маршруты новых страниц

Файл: `cabinet/urls.py`.

Добавить:

```python
path("bonuses/tasks/", bonus_views.daily_tasks, name="bonus_tasks"),
path("bonuses/levels/", bonus_views.bonus_levels, name="bonus_levels"),
path("referrals/", referral_views.referrals, name="referrals"),
```

Оставить:

```python
path("bonuses/", bonus_views.bonuses, name="bonuses"),
path("bonuses/daily-tasks/<int:task_id>/claim/", bonus_views.daily_task_claim, name="daily_task_claim"),
path("referrals/stats/", referral_views.referral_stats, name="referral_stats"),
```

`referral_stats` можно оставить для AJAX/совместимости, но новая страница `/cabinet/referrals/` должна быть SSR.

## Шаг 2. Обновить меню кабинета

Файл: `templates/cabinet/includes/_profile_tab_links.html`.

Заменить один пункт `Мои бонусы` на группу простых ссылок:

- `Мои бонусы` → `{% url 'cabinet:bonuses' %}`, active `bonuses`;
- `Ежедневные задания` → `{% url 'cabinet:bonus_tasks' %}`, active `bonus_tasks`;
- `Уровни` → `{% url 'cabinet:bonus_levels' %}`, active `bonus_levels`;
- `Рефералы` → `{% url 'cabinet:referrals' %}`, active `referrals`.

Не делать вложенное меню. Просто 4 ссылки в текущем списке.

Важно:

- ссылки должны работать и в sidebar, и в mobile tabs, потому что оба места include-ят `_profile_tab_links.html`;
- использовать существующую структуру `<a>`, `.matches-table-scope-icon`, `.matches-table-scope-copy`;
- иконки можно взять простыми inline svg по аналогии с текущими пунктами;
- не добавлять новые JS-табы.

## Шаг 3. Отключить старую JS-вкладку рефералов

Сейчас рефералы добавляются через JS:

- `front/static/front/js/profile-menu.js` динамически подключает `profile-referrals.js`;
- `front/static/front/js/profile-referrals.js` сам добавляет пункт меню и панель.

После SSR-страницы это больше не нужно.

Файл: `front/static/front/js/profile-menu.js`.

Удалить или отключить блок:

```js
(() => {
    if (!document.querySelector(".profile-page")) return;
    if (document.querySelector("script[data-profile-referrals-script]")) return;
    const script = document.createElement("script");
    script.src = "/static/front/js/profile-referrals.js";
    script.dataset.profileReferralsScript = "true";
    document.body.appendChild(script);
})();
```

Файл `front/static/front/js/profile-referrals.js` не удалять сразу, чтобы не ломать кеш/старые ссылки. Просто перестать подключать.

## Шаг 4. Сделать общую обёртку страниц кабинета бонусов

Чтобы не дублировать sidebar и mobile tabs, создать include:

Файл: `templates/cabinet/includes/_cabinet_shell_start.html` НЕ создавать, если это усложнит.

Лучше проще: в каждой новой странице скопировать минимальный каркас из `templates/cabinet/bonuses.html`:

```django
<section class="profile-page matches-page container">
    <div class="matches-shell">
        {% include "cabinet/includes/_profile_tabs_sidebar.html" %}
        <section class="matches-list-panel profile-page bonus-detail-main">
            <div class="matches-mobile-scope-panel" aria-label="{{ page.mobile_nav_label }}">
                <nav class="matches-tabs" aria-label="{{ page.profile_nav_label }}">
                    {% include "cabinet/includes/_profile_tab_links.html" with profile_tab_link_class="" %}
                </nav>
            </div>
            ...
        </section>
    </div>
</section>
```

Не делать абстрактный layout include, пока страниц всего 3 и структура может отличаться.

## Шаг 5. Добавить context builder для страницы ежедневных заданий

Файл: `cabinet/services/bonus_center.py`.

Добавить функцию:

```python
def build_bonus_tasks_page_context(user, request=None) -> dict:
    ...
```

Она должна вернуть:

- `page.title`
- `page.heading`
- `page.description`
- `page.mobile_nav_label`
- `page.profile_nav_label`
- `daily_tasks_card`
- `tasks`
- `streak_card`
- `level_progress`
- `recent_gifts`

`tasks` брать из `build_daily_tasks_card(user)["tasks"]`.

Для каждого task в context должны быть готовые поля:

- `id`
- `title`
- `description`
- `current_value`
- `target_value`
- `progress_percent`
- `status`
- `status_label`
- `reward_label`
- `can_claim`
- `claim_url`

`claim_url` сформировать через:

```python
reverse("cabinet:daily_task_claim", kwargs={"task_id": task["id"]})
```

Не строить URL в template.

## Шаг 6. Добавить view страницы ежедневных заданий

Файл: `cabinet/bonus_views.py`.

Добавить:

```python
@login_required
def daily_tasks(request):
    record_daily_task_action(request.user, DailyTask.TaskType.DAILY_LOGIN)
    context = build_bonus_tasks_page_context(request.user, request=request)
    context.update({
        "active_tab": "bonus_tasks",
        "page_class": "cabinet-bonuses-page cabinet-bonus-tasks-page",
    })
    return render(request, "cabinet/bonus_tasks.html", context)
```

Импортировать `build_bonus_tasks_page_context`.

## Шаг 7. Создать template ежедневных заданий

Файл: `templates/cabinet/bonus_tasks.html`.

Структура:

- sidebar профиля;
- mobile tabs;
- hero/head:
  - `Ежедневные задания`;
  - описание;
  - summary: `N из M выполнено`;
- список заданий:
  - название;
  - описание;
  - прогресс `current/target`;
  - награда;
  - кнопка `Получить`, если `can_claim`;
  - статус `Выполнено`, если claimed;
- правый/нижний блок:
  - `Серия дней`;
  - `Прогресс уровня`;
  - `Последние подарки`.

Для claim кнопок:

```django
<button
    type="button"
    class="bonus-task-claim"
    data-bonus-task-claim
    data-url="{{ task.claim_url }}"
    {% if not task.can_claim %}disabled{% endif %}
>
    {{ task.status_label }}
</button>
```

Не использовать skeleton для claim.

## Шаг 8. JS для страницы ежедневных заданий

Файл: `front/static/front/js/roulette.js`.

Если уже есть claim logic для dashboard, расширить её, а не делать новый файл.

Добавить поддержку:

- найти все `[data-bonus-task-claim]`;
- POST на `data-url`;
- на время запроса `disabled = true`;
- при успехе обновить:
  - конкретную строку задания;
  - summary daily tasks;
  - recent gifts;
  - level progress;
  - available spins, если есть на странице;
- при ошибке показать локальный текст ошибки рядом с кнопкой.

Не использовать `window.CappersSkeleton` для claim.

## Шаг 9. Добавить context builder для страницы уровней

Файл: `cabinet/services/bonus_center.py`.

Добавить:

```python
def build_bonus_levels_page_context(user, request=None) -> dict:
    ...
```

Вернуть:

- `page.title`
- `page.heading`
- `page.description`
- `level_progress`
- `levels`
- `recent_gifts`
- `daily_tasks_card`
- `streak_card`

`levels` получить из `XpLevel.objects.filter(is_active=True).order_by("required_xp", "level", "id")`.

Для каждого уровня подготовить:

- `level`
- `title`
- `required_xp`
- `required_xp_label`
- `reward_label`
- `is_unlocked`
- `is_current`
- `is_next`
- `progress_percent`

Не делать запросы по уровням в template.

## Шаг 10. Добавить view страницы уровней

Файл: `cabinet/bonus_views.py`.

Добавить:

```python
@login_required
def bonus_levels(request):
    context = build_bonus_levels_page_context(request.user, request=request)
    context.update({
        "active_tab": "bonus_levels",
        "page_class": "cabinet-bonuses-page cabinet-bonus-levels-page",
    })
    return render(request, "cabinet/bonus_levels.html", context)
```

Импортировать `build_bonus_levels_page_context`.

## Шаг 11. Создать template уровней

Файл: `templates/cabinet/bonus_levels.html`.

Структура:

- hero/head:
  - текущий уровень;
  - XP;
  - сколько до следующего;
  - progress ring/bar;
- список всех уровней:
  - уровень;
  - название;
  - required XP;
  - награда;
  - статус: открыт / текущий / впереди;
- sidebar/нижний блок:
  - daily tasks summary;
  - streak summary;
  - recent gifts.

Для progress ring не использовать inline style.

Вариант без inline style:

- в `build_level_progress` добавить `progress_bucket`: 0, 10, 20 ... 100;
- в template:

```django
<div class="bonus-progress-ring is-progress-{{ level_progress.progress_bucket }}">
```

- в `main.css` прописать классы `is-progress-0 ... is-progress-100`.

## Шаг 12. Рефералы перевести на SSR-страницу

Файл: `cabinet/referral_views.py`.

Добавить view:

```python
@login_required
@require_GET
def referrals(request):
    context = build_referrals_page_context(request.user, request=request)
    context.update({
        "active_tab": "referrals",
        "page_class": "cabinet-referrals-page",
    })
    return render(request, "cabinet/referrals.html", context)
```

Не удалять `referral_stats`, но новая страница не должна зависеть от JS fetch.

## Шаг 13. Создать service/context builder для рефералов

Файл: `cabinet/services/referral_bonuses.py`.

Добавить:

```python
def build_referrals_page_context(user, request=None) -> dict:
    ...
```

Использовать существующую логику из `referral_stats`, но вернуть context для template.

Context:

- `page.title`
- `page.heading`
- `page.description`
- `referral_url`
- `referral_code`
- `can_earn_referrals`
- `referral_income_display`
- `visitors_count`
- `clicks_count`
- `registrations_count`
- `subscriptions_count`
- `conversion`
- `bonus_settings`
- `bonus_cards`
- `recent_visits`
- `recent_bonus_events`

Для `recent_visits` подготовить:

- `username`
- `name`
- `visits_count`
- `first_seen_label`
- `last_seen_label`
- `registered`
- `registered_label`
- `subscribed`
- `subscribed_label`
- `status`
- `status_label`

Для `recent_bonus_events` брать:

```python
BonusEvent.objects.filter(user=user, event_type=BonusEvent.EventType.REFERRAL)
```

Ограничить до 20-40 записей.

## Шаг 14. Обновить `referral_stats`, чтобы не было дубля логики

Файл: `cabinet/referral_views.py`.

Сейчас `referral_stats` сам считает всё.

После добавления `build_referrals_page_context`:

- `referral_stats` должен вызвать этот builder;
- вернуть JSON из уже готового context;
- не дублировать расчёты.

Так слабый ИИ не должен поддерживать две разные логики.

## Шаг 15. Создать template рефералов

Файл: `templates/cabinet/referrals.html`.

Структура:

- sidebar профиля;
- mobile tabs;
- hero:
  - заголовок `Рефералы`;
  - описание;
  - поле с реферальной ссылкой;
  - кнопка копирования;
- stats grid:
  - уникальные посетители;
  - все переходы;
  - регистрации;
  - подписки;
  - конверсия;
  - заработано;
- блок “Бонусная модель”:
  - за регистрацию;
  - за первое пополнение;
  - за первую подписку;
  - проценты заработка, если пользователь каппер;
- recent visits table/list;
- recent referral bonuses list.

Копирование ссылки можно сделать маленьким JS без skeleton.

## Шаг 16. JS для SSR-рефералов

Файл: `front/static/front/js/profile-referrals.js`.

Переделать файл:

- не создавать вкладку;
- не fetch-ить `/cabinet/referrals/stats/` для построения страницы;
- работать только если есть `[data-referrals-page]`;
- обрабатывать кнопку `[data-referral-copy]`;
- показывать текст `Скопировано` / `Не удалось`.

Файл: `front/static/front/js/profile-menu.js`.

- больше не подключать `profile-referrals.js` на всех `.profile-page`;
- подключить его только на странице, где есть `[data-referrals-page]`, или подключить script прямо в `templates/cabinet/referrals.html` через `{% block extra_js %}`.

Предпочтительно: подключить в `referrals.html`, чтобы не грузить JS на все страницы профиля.

## Шаг 17. CSS для новых страниц

Файл: `front/static/front/css/main.css`.

Добавить стили рядом с текущими `.cabinet-bonuses-page` и `.profile-referrals-*`.

Новые классы:

- `.bonus-detail-main`
- `.bonus-page-head`
- `.bonus-page-summary`
- `.bonus-task-list`
- `.bonus-task-row`
- `.bonus-task-meta`
- `.bonus-task-progress-bar`
- `.bonus-task-claim`
- `.bonus-levels-hero`
- `.bonus-levels-list`
- `.bonus-level-row`
- `.cabinet-referrals-page`
- `.referrals-page-shell`
- `.referrals-hero`
- `.referrals-stats`
- `.referrals-bonus-grid`
- `.referrals-visits-list`
- `.referrals-bonus-events`

Правила:

- без `border`;
- без inline styles;
- без новых CSS-файлов;
- не добавлять `@media` в `main.css`;
- использовать фирменные цвета;
- не плодить классы, если подходит существующий `.profile-referral-*`.

Важно: старые `.profile-referrals-*` можно переиспользовать или переименовать постепенно. Не держать две одинаковые системы стилей.

## Шаг 18. Mobile CSS

Файл: `front/static/front/css/mobile.css`.

Добавить адаптивы:

- задачи в одну колонку на телефоне;
- уровни в одну колонку;
- таблицу/список рефералов сделать карточками;
- поле реферальной ссылки и кнопка копирования в колонку;
- не добавлять media query в `main.css`.

## Шаг 19. Связать dashboard cards с новыми страницами

Файл: `cabinet/services/bonus_center.py`.

В `build_bonus_center_context`:

- `daily_tasks_card.url = reverse("cabinet:bonus_tasks")`;
- `daily_tasks_card.link_label = "Открыть ежедневные задания"`;
- `streak_card` оставить без отдельной страницы или ссылать на `bonus_tasks`;
- карточку уровней сделать ссылкой на `reverse("cabinet:bonus_levels")`;
- `referral_card.url = reverse("cabinet:referrals")`, а не сама referral URL.

Важно: реферальную ссылку копировать на странице `/cabinet/referrals/`, а карточка dashboard должна вести на страницу рефералов.

## Шаг 20. Обновить `_bonus_dashboard_card.html`

Файл: `templates/cabinet/includes/_bonus_dashboard_card.html`.

Проверить:

- если `card.url` есть, arrow должен быть `<a>`;
- если URL нет, arrow остаётся `<span>`;
- для referral card ссылка должна вести в кабинет, а не наружу;
- не оборачивать всю карточку ссылкой, чтобы не ломать кнопки/JS.

## Шаг 21. Поддержка новых фич в рефералах

Файл: `cabinet/services/referral_bonuses.py`.

В `build_referrals_page_context` показать:

- бонус за регистрацию из `ReferralBonusSettings.registration_reward_coins` и `registration_reward_xp`;
- бонус за первое пополнение из `first_topup_reward_coins`;
- бонус за первую подписку из `first_subscription_reward_coins`;
- `max_visible_reward_text`;
- если `is_enabled=False`, отдать `is_disabled=True` и понятный status label.

Для капперов дополнительно показать реальный заработок в рублях:

- использовать `RealBalanceTransaction` с kind:
  - `REFERRAL_SUBSCRIPTION`;
  - `REFERRAL_TOURNAMENT`;
  - `REFERRAL_BALANCE_TOP_UP`.

Для обычных пользователей показать только бонусы платформы, без блока “заработано ₽”, если `can_earn_referrals=False`.

## Шаг 22. Breadcrumb/title/context processors не трогать без необходимости

Не добавлять SEO/страницы в `pages`, если эти страницы закрыты логином.

Достаточно:

- block title в template;
- `page_class`;
- `active_tab`.

## Шаг 23. Тесты минимально

Файл: `cabinet/tests/test_bonus_center.py` или новый `cabinet/tests/test_bonus_pages.py`.

Добавить:

- `/cabinet/bonuses/tasks/` требует login;
- `/cabinet/bonuses/tasks/` отдаёт разные задания для capper и reader;
- `/cabinet/bonuses/levels/` показывает текущий уровень;
- `/cabinet/referrals/` отдаёт referral URL и stats;
- `referral_stats` и SSR context считают одинаковые ключевые метрики.

Если времени мало, тестировать хотя бы view status code и context keys.

## Шаг 24. Ручная проверка

После изменений:

```bash
python manage.py migrate
python manage.py seed_bonus_center
```

Проверить:

- `/cabinet/bonuses/`;
- `/cabinet/bonuses/tasks/`;
- `/cabinet/bonuses/levels/`;
- `/cabinet/referrals/`;
- обычный пользователь видит reader + all задания;
- каппер видит capper + all задания;
- пункт `Рефералы` больше не создаётся через JS;
- копирование referral URL работает;
- claim задания работает без skeleton;
- меню active state работает и в sidebar, и в mobile tabs.

## Что не делать

- Не делать отдельную страницу серии дней сейчас.
- Не строить страницы через JS после загрузки.
- Не оставлять рефералы как динамическую вкладку в профиле.
- Не дублировать расчёты `referral_stats` и SSR-страницы.
- Не создавать новые CSS-файлы.
- Не использовать skeleton для claim/copy/referral small actions.
- Не делать универсальный конструктор страниц ради этих трёх страниц.
